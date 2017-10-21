#!/usr/bin/env python2
# -*- coding: UTF-8 -*-
from __future__ import print_function, division
import re
import subprocess
import json
import os
import sys
import tempfile
import time
from glob import glob
import logging
import logging.handlers
import shutil
from datetime import datetime
from io import open
import argparse
from MythTV import Recorded, Program, MythDB, VideoGrabber, Job, findfile
from MythTV.ttvdb import tvdb_api, tvdb_exceptions


class DictToNamespace(dict):
    """ convert a dictionary and any nested dictionaries to namespace"""
    def __init__(self, data, **kwargs):
        super(DictToNamespace, self).__init__(**kwargs)
        for k, v in data.items():
            if isinstance(v, dict):
                self.__setattr__(str(k), DictToNamespace(v))
                self.__setitem__(str(k), DictToNamespace(v))
            else:
                try:
                    v = float(v)
                    if float(v).is_integer():
                        v = int(v)
                except (TypeError, ValueError):
                    pass
                self.__setitem__(str(k), v)
                self.__setattr__(str(k), v)


config_dict = {'file': {'fileformat': 'mp4', 'logdir': '/',
                        'exportdir': '/', 'fallbackdir': '/', 'saveold': 1,
                        'usecommflag': 0, 'tvdirstruct': 'folders',
                        'mvdirstruct': 'none', 'commethod': 'remove',
                        'includesub': 0, 'export': 1, 'exporttype': 'kodi',
                        'episodetitle': 1, 'allowsearch': 0
                        },
               'video': {'codechd': 'libx264', 'codecsd': 'libx264',
                         'presethd': 'medium', 'presetsd': 'medium',
                         'crfhd': 20, 'crfsd': 18, 'minratehd': 0,
                         'minratesd': 0, 'maxratehd': 0, 'maxratesd': 0,
                         'deinterlacehd': 'yadif', 'deinterlacesd': 'yadif'
                         },
               'audio': {'codechd': 'aac', 'codecsd': 'aac', 'bpchd': 64,
                         'bpcsd': 64, 'language': 'eng'
                         }
               }
conf_path = os.path.dirname(__file__)
config_file = '{}/conf.json'.format(conf_path)


class ConfigSetup:
    """
    Load configuration file in json format. If no configuration file exists
    a defaults dictionary is used to create one
    """

    def __init__(self, configuration_file, defaults=None):
        # Write default config file if none exists
        self.file = None
        self.video = None
        self.audio = None
        if not os.path.isfile(configuration_file):
            with open(configuration_file, 'wb') as conf_write:
                json.dump(defaults, conf_write)
        config = {}
        config_out = {}
        # Set config dict to values in config file
        with open(configuration_file, 'rb') as conf_read:
            config.update(json.load(conf_read))

        if config.keys() == defaults.keys():
            for section, items in config.items():
                config_out.update({str(section): {}})
                if isinstance(items, dict):
                    for k, v in items.items():
                        if k in ['exportdir', 'fallbackdir']:
                            if not v.endswith('/'):
                                v = '{}/'.format(v)
                        k = str(k)
                        if not isinstance(v, (int, float)):
                            v = str(v)
                            items.update({str(k): str(v)})
                            config_out[str(section)].update({str(k): str(v)})
                        else:
                            config_out[str(section)].update({str(k): v})
                if config_dict[section].keys() != items.keys():
                    invalid = ([item for item in items.keys()
                                if item not in config_dict[section].keys()])
                    missing = ([item for item in config_dict[section].keys()
                                if item not in items.keys()])
                    if invalid:
                        for item in invalid:
                            print('Invalid entry in configuration file: {}'
                                  .format(item)
                                  )
                    if missing:
                        for item in missing:
                            print('Missing entry in configuration file: {}'
                                  .format(item)
                                  )
        for k, v in config_out.items():
            setattr(self, k, DictToNamespace(v))


settings = ConfigSetup(config_file, defaults=config_dict)


def write_check(path):
    """Check if a directory is writeable if not return False."""
    import errno
    if not path.endswith('/'):
        path = '{}/'.format(path)
    test_file = '{}.test'.format(path)
    try:
        open(test_file, 'w')
    except IOError as e:
        if e.errno == errno.EACCES:
            return False
        else:
            raise IOError(e.errno, e.strerror)
    else:
        os.remove(test_file)
        return True


# *** logging setup ***
logdir = settings.file.logdir
if logdir is '/':
    logdir = settings.file.logdir
logfile = '{}/transcode.log'.format(logdir)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
lf = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
# setup console logging
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(lf)
logger.addHandler(ch)
# Setup file logging
try:
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    if write_check(logdir):
        fh = logging.handlers.TimedRotatingFileHandler(
            filename=logfile, when='W0', interval=1, backupCount=10)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(lf)
        logger.addHandler(fh)
    if not write_check(logdir):
        logging.error('logfile not accessible:{}'.format(logdir))
except Exception as e:
    logging.error('logfile not accessible:{}'.format(logdir))
    logging.error(e)
    sys.exit(1)
# *** logging setup end ***

try:
    db = MythDB()
except Exception as e:
    logging.error(e)
    sys.exit(1)


def program_check(program, alt_program=None):
    """
    Check if program or  optional alternate program is installed. returning
    the path to the programs executable
    """
    from distutils import spawn
    if spawn.find_executable(program):
        return spawn.find_executable(program)
    if alt_program:
        if spawn.find_executable(alt_program):
            return spawn.find_executable(alt_program)
    else:
        if alt_program:
            raise LookupError('Unable to find {} or {}'.format(program,
                                                               alt_program
                                                               )
                              )
        if not alt_program:
            raise LookupError('Unable to find {}'.format(program))


def get_free_space(path):
    """Get available space in path"""
    st = os.statvfs(path)
    fs = (st.f_bavail * st.f_frsize) / 1024
    return fs


class AVInfo(dict):
    """
    identify A/V configuration of input file and returns
    self.video dict a list of self.audio.stream dicts,
    and self.duration as float
    """
    ffprobe = program_check('ffprobe', 'mythffprobe')

    def __init__(self=None, input_file=None, **kwargs):
        super(AVInfo, self).__init__(**kwargs)
        self.audio = None
        self.duration = None
        self.video = None
        command = [self.ffprobe, '-v', '-8', '-show_entries',
                   'stream=codec_type,index,codec_name,channels,width,'
                   'height,r_frame_rate:stream_tags=language:'
                   'format=duration', '-of', 'csv=nk=0:p=0', input_file
                   ]
        x = subprocess.check_output(command).split('\n')

        vcd = {}
        adict = {}
        dur = 0
        for vc in x:
            if 'codec_type=video' in vc:
                for item in vc.split(','):
                    k, v = item.split('=')
                    if k == 'r_frame_rate':
                        k = 'frame_rate'
                        v = int(v.split('/')[0]) / int(v.split('/')[1])
                    if k == 'index':
                        k = 'stream_index'
                    vcd.update({k: v})
        for ac in x:
            if 'codec_type=audio' in ac:
                items = [item.split('=') for item in ac.split(',')]
                streamdict = {k.strip(): v.strip() for (k, v) in items}

                if 'tag:language' in streamdict.keys():
                    streamdict['language'] = (streamdict.pop
                                              ('tag:language')
                                              )
                adict.update({'stream{}'.format(streamdict['index'])
                              : streamdict})
                if 'index' in streamdict.keys():
                    streamdict['stream_index'] = (streamdict.pop('index'))
                adict.update({'stream{}'.format(streamdict['stream_index'])
                              : streamdict})

        for d in x:
            if d.startswith('duration='):
                dur = float(d.split('=')[1])

        self.__setattr__('video', DictToNamespace(vcd))
        self.__setitem__('video', DictToNamespace(vcd))
        self.__setattr__('duration', dur)
        self.__setitem__('duration', dur)
        self.__setitem__('audio', DictToNamespace(adict))
        self.__setattr__('audio', DictToNamespace(adict))


def temp_check(tmpdir):
    """Create or clear temporary directory"""
    try:
        if os.path.isdir(tmpdir):
            logging.info('chk:temp Folder found:{}'.format(tmpdir))
            if os.listdir(tmpdir) != 0:
                logging.warning('chk:Temp folder not empty!: '
                                'Removing Files:{}'.format(tmpdir)
                                )
                shutil.rmtree(tmpdir)
                os.makedirs(tmpdir)
        if not os.path.isdir(tmpdir):
            logging.info('chk:no temp folder found:{}'.format(tmpdir))
            os.makedirs(tmpdir)
            logging.info('chk:Temp folder created:{}'.format(tmpdir))
    except Exception as e:
        print(e)
        logging.error(e)


def remove_temp(tmpdir):
    """Remove temporary directory"""
    try:
        if os.path.isdir(tmpdir):
            logging.info('rem:temp Folder found:{}'.format(tmpdir))
            shutil.rmtree(tmpdir)
        if not os.path.isdir(tmpdir):
            logging.info('rem:temp Folder Removed:{}'.format(tmpdir))
            pass
    except Exception as e:
        print(e)
        logging.error(e)


class FileSetup:
    """
    Configure filename and directory structure to self.filename
    and self.directory. using program-id to identify the output format.
    """
    def __init__(self, settings, metadata):
        # clean special characters from file/directory names
        # using dict to make adding replacements simple
        # may need to add several for windows compatibility
        replace_dict = {'/': ' and '}
        title = metadata.title
        subtitle = metadata.subtitle
        for replace_title in title:
            if replace_title in replace_dict.keys():
                title = title.replace(replace_title,
                                      replace_dict[replace_title]
                                      )
        for replace_subtitle in subtitle:
            if replace_subtitle in replace_dict.keys():
                print(replace_dict.keys())
                subtitle = subtitle.replace(replace_subtitle,
                                            replace_dict[replace_subtitle])
        mv_dir = settings.file.mvdirstruct
        tv_dir = settings.file.tvdirstruct
        program_id = metadata.programid
        date = metadata.starttime.strftime('%Y.%m.%d')
        sep = ''
        if settings.file.exporttype == 'kodi':
            sep = '_'
        if settings.file.exporttype == 'plex':
            sep = ' - '
        if program_id.startswith('EP'):
            logging.info('File setup: program identified as TV episode')
            if tv_dir == 'none':
                self.directory = ''
            if tv_dir == 'folders':
                self.directory = ('TV shows/{}/season {:02d}/'
                                  .format(title, metadata.season)
                                  )
            if settings.file.episodetitle:
                self.filename = ('{}{}S{:02d}E{:02d}{}{}'
                                 .format(title, sep, metadata.season,
                                         metadata.episode, sep,
                                         subtitle
                                         )
                                 )
            if not settings.file.episodetitle:
                self.filename = ('{}{}S{:02d}E{:02d}'
                                 .format(title, sep, metadata.season,
                                         metadata.episode
                                         )
                                 )
        # Movie setup
        if program_id.startswith('MV'):
            logging.info('File setup: program identified as Movie')
            if metadata.year != metadata.starttime.year:
                self.filename = '{}({})'.format(title, metadata.year)
                if mv_dir == 'folders':
                    # may want/need to validate year?
                    self.directory = 'Movies/{}({})/'.format(title,
                                                             metadata.year
                                                             )
            else:
                self.filename = '{}'.format(title)
                if mv_dir == 'folders':
                    # may need to validate year?
                    self.directory = 'Movies/{}/'.format(title)
            if mv_dir == 'none':
                self.directory = ''

        # Unknown setup
        if program_id is 'UNKNOWN':
            logging.info('File setup: Program ID unknown')
            self.directory = ''
            if metadata.subtitle is not '':
                self.filename = '{}{}{}{}{}'.format(title, sep,
                                                    subtitle, sep,
                                                    date
                                                    )
            else:
                self.filename = '{}{}{}'.format(title, sep, date)


def export_file(input_file, output_dir):
    """
    Transfer file to output_dir, preforming hash verification to confirm
    successful transfer. If verification fails a fallback.log file will be
    created in the input_files directory. If the fallback.log file exists
    any files listed within will be transferred
    """
    input_name = input_file.split('/')[-1]
    input_dir = '{}/'.format(os.path.dirname(input_file))
    fallback_log = '{}fallback.log'.format(input_dir)
    output_file = '{}{}'.format(output_dir, input_name)

    def comp_hash(input_one, input_two, buffer_size=None):
        """compare the hash value of two files"""
        def sha1_hash(file_path, buf_size=None):
            """generate sha1 hash from input"""
            import hashlib
            if not buf_size:
                buf_size = 65536
            else:
                buf_size = buf_size
            sha1 = hashlib.sha1()
            with open(file_path, 'rb') as f:
                while True:
                    data = f.read(buf_size)
                    if not data:
                        break
                    sha1.update(data)
            return sha1.hexdigest()
        hash_one = sha1_hash(input_one, buf_size=buffer_size)
        hash_two = sha1_hash(input_two, buf_size=buffer_size)
        if hash_one == hash_two:
            return True
        else:
            return False
    # Check for fallback log and process any entries
    fallback_list = []
    if os.path.isfile(fallback_log):
        logging.info("Fallback log detected processing entry's")
        with open(fallback_log, 'r') as input_files:
            files = input_files.readlines()
            for old_file in files:
                old_file = old_file.rstrip('\n')
                old_name = old_file.split('/')[-1]
                old_dir = old_file.rstrip(old_name)
                fallback_file = '{}{}'.format(input_dir, old_name)
                if not os.path.isdir(old_dir):
                    os.makedirs(old_dir)
                if os.path.isdir(old_dir):
                    if write_check(old_dir):
                        if not os.path.isfile(old_file):
                            if os.path.isfile(fallback_file):
                                shutil.copyfile(fallback_file, old_file)
                                successful_transfer = comp_hash(fallback_file,
                                                                old_file
                                                                )
                                if not successful_transfer:
                                    # hash check failed add to fallback list
                                    logging.error('Hash verification failed'
                                                  ' for: {}'.format(old_file)
                                                  )
                                    fallback_list.append(old_file)
                                    # Should log reason?
                                if successful_transfer:
                                    logging.info('Hash verification sucessful'
                                                 ' for: {}'.format(old_file)
                                                 )
                                    os.remove(fallback_file)
    if not os.path.isdir(output_dir):
        logging.info('Creating export directory')
        os.makedirs(output_dir)
    if os.path.isdir(output_dir):
        logging.info('Copying file to export directory')
        shutil.copyfile(input_file, output_file)
        logging.info('Start hash verification')
        successful_transfer = comp_hash(input_file, output_file)
        if not successful_transfer:
            logging.error('Hash verification failed')
            fallback_list.append(output_file)
        if successful_transfer:
            logging.info('Hash verification sucessfull')
            os.remove(input_file)

    if fallback_list:
        with open(fallback_log, 'w') as write_fallback:
            for item in fallback_list:
                write_fallback.write(u'{}\n'.format(item))
    if not fallback_list and os.path.isfile(fallback_log):
        os.remove(fallback_log)


def frames_to_time(cut_frames, frame_rate, frame_offset=0):
    """
    Convert a list of frames to a list of times using The
    frame-rate of the intended video file.
    a frame offset can be used to shift the time for more
    accurate times
    """
    cut_times = []
    for start, end in cut_frames:
        if frame_offset != 0:
            start = start + frame_offset
            end = end + frame_offset
        cut_times.append((start / frame_rate, end / frame_rate))
    return cut_times


def generate_concat_filter(segment_list, avinfo):
    """
    Generate FFMpeg filter complex using a list of tuples containing
    start and end times of the desired segments. an AVInfo() instance
    is used to identify the audio streams.
    returns a tuple of filter complex, video map, audio map list
    video map and audio map list are the outputs of the filter complex
    """

    count = 0
    filter_list = []
    concat_list = []
    video_map = ''
    audio_list = []

    for start, end in segment_list:
        filter_string = ('[0:0]trim=start={}:end={},setpts=PTS-STARTPTS[v{}]'
                         .format(start, end, count)
                         )
        audio_string = ''
        for stream in avinfo.audio.keys():
            stream_index = avinfo.audio[stream].stream_index
            if audio_string is '':
                audio_string = ('[0:{}]atrim=start={}:end={},'
                                'asetpts=PTS-STARTPTS[a{}s{}]'.format(
                                 stream_index, start, end, count, stream_index))
            else:
                if (stream_index < re.search('\[0:\d\]',
                                             audio_string).group(0)[4]):
                    audio_string = ('[0:{}]atrim=start={}:end={},'
                                    'asetpts=PTS-STARTPTS[a{}s{}];{}'.format(
                                        stream_index, start, end, count,
                                        stream_index, audio_string)
                                    )
                else:
                    audio_string = ('{};{}'.format(
                        audio_string, '[0:{}]atrim=start={}:end={},'
                                      'asetpts=PTS-STARTPTS[a{}s{}]'.format(
                                            stream_index, start, end, count,
                                            stream_index))
                                    )

        video_id = ''.join(re.findall('\[v\d{1,2}\]', filter_string))
        audio_id = ''.join(re.findall('\[a\d{1,2}s\d\]', filter_string))
        concat_list.append('{}{}'.format(video_id, audio_id))
        filter_list.append('{};{}'.format(filter_string, audio_string))
        count = count + 1

    concat_string_list = []
    last_concat = ''
    count_two = 0
    for item in filter_list:
        audio_concat_string = ''
        video_id = re.findall('\[v\d{1,2}\]', item)
        audio_id = re.findall('\[a\d{1,2}s\d\]', item)
        concat_id = '{}{}'.format(''.join(video_id), ''.join(audio_id))

        if last_concat is '':
            last_concat = concat_id
        else:
            for audio_stream in audio_id:
                audio_concat_string = ('{}{}'.format(audio_concat_string,
                                                     '[ac{}s{}]'.format(
                                                         count_two,
                                                         audio_stream[-2]))
                                       )

            last_concat = ('{}{}concat=v=1:a={}[vc{}]{}'
                           .format(last_concat, concat_id, len(audio_id),
                                   count_two, audio_concat_string
                                   )
                           )
            concat_string_list.append(last_concat)
            last_concat = '[vc{}]{}'.format(count_two, audio_concat_string)

        if item == filter_list[-1]:
            audio_list.extend(re.findall('\[ac\d{1,2}s\d\]',
                                         audio_concat_string
                                         )
                              )
            video_map = '[vc{}]'.format(count_two)
        count_two = count_two + 1

    concat_filter = ''
    if concat_filter == '':
        concat_filter = ('{};{};{}'.format(filter_list.pop(0),
                                           filter_list.pop(0),
                                           concat_string_list.pop(0))
                         )

    while len(filter_list) >= 1:
        concat_filter = ('{};{}'.format(concat_filter,
                                        '{};{}'.format(filter_list.pop(0),
                                                       concat_string_list.pop(0)
                                                       )
                                        )
                         )

    return concat_filter, video_map, audio_list


def get_episode(series_title, episode_title=None, season_number=None,
                episode_number=None, episode_separator=';',
                part_separator='Part'):
    """
    Retrieve and return a list of TV episode(s) metadata using ttvdb.tvdb_api.

    episode_separator: character used for multiple episode subtitles

    part_separator: character(s) used to separate episode subtitle from
     episode part number. may need for non-english use?
    """
    t = tvdb_api.Tvdb()
    numerals = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7,
                'VIII': 8, 'IX': 7, 'X': 10
                }
    numbers_word = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
                    }
    episode_list = []

    if episode_title:
        if episode_separator and episode_separator in episode_title:
            episode_split = episode_title.split(episode_separator)
            for episode in episode_split:
                try:
                    episode_result = (
                        get_episode(series_title, episode,
                                    episode_separator=episode_separator,
                                    part_separator=part_separator
                                    )
                    )
                except (tvdb_exceptions.tvdb_shownotfound,
                        tvdb_exceptions.tvdb_episodenotfound) as e:
                    print(e)
                    continue
                if episode_result not in episode_list:
                    episode_list.extend(episode_result)
            return episode_list

        if part_separator and part_separator in episode_title:
            part_split = episode_title.split('Part')
            print(part_split)
            part_title = part_split[0].rstrip()
            part_number = part_split[-1].strip()
            if part_number.isdigit():
                part_number = int(part_number)
            if part_number in numerals.keys():
                part_number = numerals[part_number]
            if part_number.lower() in numbers_word.keys():
                part_number = numbers_word[part_number.lower()]
            try:
                result = t[series_title].search(part_title, key='episodename')
                if len(result) >= 2:
                    for match in result:
                        if (match['episodename']
                                .endswith('({})'.format(part_number))):
                            episode_list.append(match)
                if len(result) == 1:
                    episode_list.extend(result)

            except (tvdb_exceptions.tvdb_shownotfound,
                    tvdb_exceptions.tvdb_seasonnotfound,
                    tvdb_exceptions.tvdb_episodenotfound) as e:
                print(e)
                try:
                    result = t[series_title].search(part_title,
                                                    key='episodename'
                                                    )
                    if len(result) == 1:
                        episode_list.extend(result)
                except (tvdb_exceptions.tvdb_shownotfound,
                        tvdb_exceptions.tvdb_seasonnotfound,
                        tvdb_exceptions.tvdb_episodenotfound) as e:
                    print(e)

        else:
            episode_result = (t[series_title].search(episode_title,
                                                     key='episodename'
                                                     )
                              )
            if len(episode_result) == 1 and episode_result not in episode_list:
                episode_list.extend(episode_result)
            if len(episode_result) == 0:
                episode_result = (t[series_title].search(episode_title))
                if len(episode_result) == 1:
                    episode_list.extend(episode_result)

    if season_number and episode_number:
        try:
            episode_list.append(t[series_title][season_number][episode_number])
        except (tvdb_exceptions.tvdb_shownotfound,
                tvdb_exceptions.tvdb_seasonnotfound,
                tvdb_exceptions.tvdb_episodenotfound) as e:
            return e
    for item in episode_list:
        for k, v in item.items():
            if k == 'episodenumber':
                item.update({'episode': int(item.pop(k))})
            if k == 'seasonnumber':
                item.update({'season': int(item.pop(k))})
            if k == 'firstaired':
                item.update({'originalairdate': datetime.strptime(item.pop(k),
                                                                  '%Y-%m-%d')
                            .date()
                             }
                            )
                item.update({'airdate': item['originalairdate']})
                item.update({'year': item['originalairdate'].year})
            if k == 'overview':
                item.update({'description': str(item.pop(k).encode('UTF-8'))})
            if k == 'episodename':
                item.update({'subtitle': str(item.pop(k).encode('UTF-8'))})
            if k == 'rating':
                item.update({'stars': float(item.pop(k))})

    return episode_list


def get_movie(title, year=None):
    """Use MythTV video grabber to retrieve movie metadata."""
    movie_grabber = VideoGrabber('movie')
    movie_search = list(movie_grabber.search(title))
    movie_result = []
    result_len = len(movie_search)
    for result in movie_search:
        if result_len > 1:
            if year is not None and year == result['year']:
                movie_result.append(result)
            elif result.title == title:
                movie_result.append(result)
        if result_len == 1:
            movie_result = result
        if result_len == 0:
            print('Unable to locate Movie: {}'.format(title))
    if len(movie_result) == 1:
        return movie_result[0]
    else:
        return {}


class RecordingToMetadata:
    """
    Retrieve required metadata from the MythTV database
    allow_search[bool] option to allow metadata search for missing programid
    """
    def __init__(self, recorded, allow_search=False):
        self.title = u''
        self.subtitle = u''
        self.starttime = None
        self.description = u''
        self.season = 0
        self.episode = 0
        self.programid = u''
        self.originalairdate = None
        self.airdate = None
        self.year = None
        self.previouslyshown = None
        self.cutlists = {}
        cut_lists = {u'cut_list': None, u'uncut_list': None, u'skip_list': None,
                     u'unskip_list': None}

        program = Program.fromRecorded(recorded)
        for k, v in recorded.items():
            if k in self.__dict__.keys():
                if v not in ['', None]:
                    setattr(self, k, v)
        for k, v in program.items():
            if k in self.__dict__.keys():
                if v not in ['', None]:
                    setattr(self, k, v)

        self.title = u'{}'.format(self.title)
        self.subtitle = u'{}'.format(self.subtitle)
        self.description = u'{}'.format(self.description)
        if recorded.cutlist:
            cut_lists['cut_list'] = recorded.markup.getcutlist()
            cut_lists['uncut_list'] = recorded.markup.getuncutlist()
        if recorded.commflagged == 1:
            cut_lists['skip_list'] = recorded.markup.getskiplist()
            cut_lists['unskip_list'] = recorded.markup.getunskiplist()
        self.cutlists = DictToNamespace(cut_lists)
        # if no programid is found attempt internet search to identify
        #  TV episode or movie using available data.
        if self.programid == u'':
            if allow_search:
                episode_data = []
                if self.subtitle != u'':
                    episode_data = get_episode(self.title,
                                               episode_title=self.subtitle
                                               )
                if self.subtitle == u'' and any([self.season, self.episode]):
                    episode_data = get_episode(self.title,
                                               season_number=self.season,
                                               episode_number=self.episode
                                               )
                if len(episode_data) == 1:
                    self.programid = u'EP'
                    for item in episode_data:
                        for k, v in item.items():
                            if k == 'airedSeason':
                                self.season = v
                            if k == 'airedEpisodeNumber':
                                self.episode = v
                            if k == 'firstAired':
                                self.originalairdate = (datetime
                                                        .strptime(v, '%Y-%m-%d')
                                                        )
                                self.year = self.originalairdate.year
                            if k is 'episodename' and self.subtitle is u'':
                                self.subtitle = u'{}'.format(v.decode('UTF-8'))
                            if k == 'description':
                                self.description = (u'{}'
                                                    .format(v.decode('UTF-8'))
                                                    )
                # multi-episode recording setup would go here
                if self.subtitle == u''\
                        and not any([self.season, self.episode]):
                    if self.year != self.starttime.year:
                        movie_data = get_movie(self.title, self.year)
                    else:
                        movie_data = get_movie(self.title)
                    if movie_data != {}:
                        self.programid = u'MV'
                        for item in movie_data:
                            for k, v in item.items():
                                if k == 'releasedate':
                                    self.originalairdate = (datetime
                                                            .strptime(v,
                                                                      '%Y-%m-%d'
                                                                      )
                                                            )
                                    self.year = self.originalairdate.year
                                if k == 'description':
                                    self.description = u'{}'.format(v)
            else:
                if self.season and self.episode:
                    self.programid = u'EP'
        if self.programid == u'':
            self.programid = u'UNKNOWN'


def update_recorded(rec, input_file, output_file):
    """
    Update MythTV database entry. clearing out old markup data and removing
    thumbnail images.
    """
    logging.info('Started: Database Recording update')

    logging.debug('rec={} input_file={} output_file={}'.format(rec, input_file,
                                                               output_file
                                                               )
                  )
    chanid = rec.chanid
    starttime = (datetime.utcfromtimestamp(rec.starttime.timestamp())
                 .strftime('%Y%m%d%H%M%S')
                 )
    logging.debug('chanid={} starttime={}'.format(chanid, starttime))
    try:
        subprocess.call(['mythutil', '--chanid', str(chanid), '--starttime',
                         str(starttime), '--clearcutlist'
                         ]
                        )
    except Exception as e:
        logging.error('Mythutil exception clearing cut-list: {}'.format(e))
    try:
        subprocess.call(['mythutil', '--chanid', str(chanid), '--starttime',
                         str(starttime), '--clearskiplist'
                         ]
                        )
    except Exception as e:
        logging.error('Mythutil exception clearing skip-list:{}'.format(e))
        pass
    for index, mark in reversed(list(enumerate(rec.markup))):
        if mark.type in (rec.markup.MARK_COMM_START, rec.markup.MARK_COMM_END):
            del rec.markup[index]
    rec.bookmark = 0
    rec.bookmarkupdate = datetime.now()
    rec.cutlist = 0
    rec.commflagged = 0
    rec.markup.commit()
    rec.basename = os.path.basename(output_file)
    rec.filesize = os.path.getsize(output_file)
    rec.transcoded = 1
    rec.seek.clean()
    rec.update()

    try:
        logging.info('Removing PNG files')
        for png in glob('{}*.png'.format(input_file)):
            os.remove(png)
    except Exception as e:
        logging.error('Error removing png files', e)
        pass
    try:
        logging.info('Removing JPG files')
        for jpg in glob('{}*.jpg'.format(input_file)):
            os.remove(jpg)
    except Exception as e:
        logging.error('Error removing jpg files', e)
        pass
    try:
        logging.info('Rebuilding seek-table')
        subprocess.call(['mythcommflag', '--chanid', str(chanid), '--starttime',
                         str(starttime), '--rebuild'
                         ]
                        )
    except Exception as e:
        logging.error('Mythcommflag ERROR clearing skip-list:{}'.format(e))
        pass


class Encoder:
    """Configure and run FFmpeg encoding"""
    ffmpeg = program_check('ffmpeg', 'mythffmpeg')

    def __init__(self, input_file, output_file, settings=None, metadata=None):
        self.input_file = input_file
        self.output_file = output_file
        self.settings = settings
        self.temp_dir = ('{}{}/'
                         .format(self.settings.file.fallbackdir,
                                 os.path.basename(input_file).rsplit('.')[0]
                                 )
                         )
        self.temp_file = ('{}{}'
                          .format(self.temp_dir,
                                  os.path.basename(input_file).rsplit('.')[0]
                                  )
                          )
        self.av_info = AVInfo(input_file)
        self.metadata = metadata
        self.metadata_file = None
        self.hd = False
        self.map_count = 0
        self.subtitle_input = None
        self.subtitle_metadata = None
        self.video_config = []
        self.audio_config = []

        if (self.av_info.video.height >= 720
                and self.av_info.video.width >= 1280):
                    self.hd = True
        else:
            self.hd = False
        # Check directory access
        if not write_check(self.settings.file.fallbackdir):
            logging.error('Fallback directory is not writable')
            sys.exit(1)
        if not write_check(self.settings.file.exportdir):
            if self.settings.file.export:
                logging.error('Export directory is not writable')
                sys.exit(1)
            else:
                logging.warning('Export directory is not writable')
        temp_check(self.temp_dir)

        def video_setup():
            """Create self.video_config list for use by ffmpeg"""
            self.video_config = ['-map', '0:0', '-filter:v', 'yadif=0:-1:1',
                                 '-movflags', 'faststart', '-forced-idr', '1',
                                 '-c:v'
                                 ]
            if self.hd:
                self.video_config.extend((self.settings.video.codechd,
                                          '-preset:v',
                                          self.settings.video.presethd,
                                          '-crf:v',
                                          str(self.settings.video.crfhd)
                                          )
                                         )
                # if max_HD != 0:
                #     max_HD = max_HD * 1000
                #     Vparam.extend(('-maxrate:v', str(max_HD), '-bufsize:v',
                #                    str(max_HD * vbuff))
                #                   )
                # if min_HD != 0:
                #     min_HD = min_HD * 1000
                #     Vparam.extend(('-minrate:v', str(min_HD)))

            elif not self.hd:
                self.video_config.extend((self.settings.video.codecsd,
                                          '-preset:v',
                                          self.settings.video.presethd,
                                          '-crf:v',
                                          str(self.settings.video.crfsd)
                                          )
                                         )
                # if max_SD != 0:
                #     max_SD = max_SD * 1000
                #     Vparam.extend(('-maxrate:v', str(max_SD), '-bufsize:v',
                #                    str(max_SD * vbuff))
                #                   )
                # if min_SD != 0:
                #     min_SD = min_SD * 1000
                #     Vparam.extend(('-minrate:v', str(min_SD)))

        def audio_setup():
            """Create self.audio_config list for use by ffmpeg"""
            self.audio_config = []
#            if self.settings.audio.language == 'all':
            audio_map_list = []
            audio_map = []
            for select in self.av_info.audio:
                audio_map.extend(['-map',
                                  '0:{}'.format(self.av_info.audio[select]
                                                .stream_index
                                                )
                                  ]
                                 )
                audio_map.append('-c:a')
                if self.hd:
                    if self.settings.audio.codechd == 'copy':
                        audio_map.append('copy')
                    elif self.settings.audio.codechd != 'copy':
                        audio_map.extend([self.settings.audio.codechd,
                                          '-b:a',
                                          str((self.settings.audio.bpchd * 1000)
                                              * self.av_info.audio[select]
                                              .channels
                                              )
                                          ]
                                         )
                if not self.hd:
                    if self.settings.audio.codecsd == 'copy':
                        audio_map.append('copy')
                    elif self.settings.audio.codecsd != 'ac3':
                        audio_map.extend([self.settings.audio.codecsd,
                                          '-b:a',
                                          str((self.settings.audio.bpcsd * 1000)
                                              * self.av_info.audio[select]
                                              .channels
                                              )
                                          ]
                                         )
                audio_map.extend(('-metadata:s:0:{}'
                                  .format(self.av_info.audio[select]
                                          .stream_index),
                                  'language={}'
                                  .format(self.av_info.audio[select].language
                                          )
                                  )
                                 )
                audio_map_list.append(audio_map)
                audio_map = []

            if self.settings.audio.language != 'all':
                for audio_select in audio_map_list:
                    if ('language={}'.format(self.settings.audio.language)
                            in audio_select):
                            self.audio_config.extend(audio_select)
                if len(self.audio_config) < 1:
                    raise ValueError('No audio streams match selected language')
            else:
                self.audio_config.extend(audio_map_list)

        def metadata_setup():
            """Create FFMetadata text file for embedding meta-data with FFmpeg
            file will be located in settings.temp_dir
            """
            metadata_file = '{}metadata.txt'.format(self.temp_dir)
            if self.metadata.programid is not u'UNKNOWN':
                with open(metadata_file, 'w') as mf:
                    mf.write(u';FFMETADATA1\n')
                    if self.settings.file.fileformat == 'mp4':
                        if (self.metadata.programid.startswith(u'EP') or any(
                                (self.metadata.season, self.metadata.episode))):
                            mf.write(u'show={}\ntitle={}\n'
                                     u'season_number={:02d}\n'
                                     u'episode_sort={:02d}\n'
                                     .format(self.metadata.title,
                                             self.metadata.subtitle,
                                             self.metadata.season,
                                             self.metadata.episode
                                             )
                                     )
                            if self.metadata.description != '':
                                mf.write(u'description={}\n'
                                         .format(self.metadata.description)
                                         )
                            if (not self.metadata.previouslyshown and
                                    self.metadata.originalairdate is None):
                                mf.write(u'date={}\n'
                                         .format(self.metadata.starttime.date())
                                         )
                            if (self.metadata.previouslyshown and
                                    self.metadata.originalairdate is not None):
                                mf.write(u'date={}\n'
                                         .format(self.metadata.originalairdate)
                                         )
                        if self.metadata.programid.startswith(u'MV'):
                            mf.write(u'title={}\n'.format(self.metadata.title))
                            if self.metadata.description != '':
                                mf.write(u'description={}\n'
                                         .format(self.metadata.description)
                                         )
                    if self.settings.file.fileformat == 'mkv':
                        if (self.metadata.programid.startswith(u'EP') or
                                any((self.metadata.season,
                                     self.metadata.episode
                                     )
                                    )):
                            mf.write(u'TITLE={}\nSUBTITLE={}\nSEASON={:02d}\n'
                                     u'EPISODE={:02d}\n'
                                     .format(self.metadata.title,
                                             self.metadata.subtitle,
                                             self.metadata.season,
                                             self.metadata.episode
                                             )
                                     )
                            if self.metadata.description != '':
                                mf.write(u'DESCRIPTION={}\n'
                                         .format(self.metadata.description)
                                         )
                            if (not self.metadata.previouslyshown and
                                    self.metadata.originalairdate is None):
                                mf.write(u'DATE_RELEASED={}\n'
                                         .format(self.metadata.starttime.date())
                                         )
                            if (self.metadata.previouslyshown and
                                    self.metadata.originalairdate is not None):
                                mf.write(u'DATE_RELEASED={}\n'
                                         .format(self.metadata.originalairdate)
                                         )
                        if self.metadata.programid.startswith(u'MV'):
                            mf.write(u'TITLE={}'.format(self.metadata.title))
                            if self.metadata.description != u'':
                                mf.write(u'DESCRIPTION={}\n'
                                         .format(self.metadata.description)
                                         )
                            if (self.metadata.year !=
                                    self.metadata.starttime.year):
                                mf.write(u'DATE_RELEASED={}\n'
                                         .format(self.metadata.year)
                                         )
                                # Need to build grabber for inet metadata

                    if self.settings.file.commethod == 'chapters':
                        chapter_list = []
                        if self.metadata.cutlists.cut_list:
                            chapter_list = [i for v in
                                            self.metadata.cutlists.cut_list
                                            for i in v
                                            ]
                        if not self.metadata.cutlists.cut_list:
                            if self.metadata.cutlists.skip_list:
                                chapter_list = [i for v in
                                                self.metadata.cutlists.skip_list
                                                for i in v
                                                ]
                        if chapter_list:
                            if chapter_list[0] != 0:
                                chapter_list = [0] + chapter_list
                            if chapter_list[-1] == 9999999:
                                chapter_list.remove(chapter_list[-1])
                            while len(chapter_list) >= 2:
                                mf.write(u'[CHAPTER]\nTIMEBASE=1/{}\nSTART={}\n'
                                         u'END={}\n'
                                         .format(self.av_info.video.frame_rate,
                                                 chapter_list[0],
                                                 chapter_list[1]
                                                 )
                                         )
                                chapter_list.remove(chapter_list[0])
            if os.path.isfile(metadata_file):
                    self.metadata_file = metadata_file
                    self.map_count = self.map_count + 1
            else:
                self.metadata_file = None

        def extract_closed_captions(input_file, output_dir):
            """Extract closed captions from input_file into .srt files
             in the output_dir
            """
            # Length of progress bar
            statlen = 10
            # Character used for progress bar
            # Use chr() in python 3
            statchar = unichr(9619).encode('UTF-8')
            # Character used to pad progress bar
            pad = ' '

            cc_extractor = program_check('mythccextractor', 'ccextractor')
            command = [cc_extractor, '-i', input_file, '-d', output_dir]
            print(subprocess.list2cmdline(command))
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen(command, stdout=output,
                                           stderr=output,
                                           universal_newlines=True
                                           )

                while True:
                    if process.poll() is not None:
                        if process.poll() != 0:
                            output.seek(0)
                            logging.error((output.read().decode('UTF-8')))
                            # print(output.read().decode('UTF-8'))
                            sys.exit(1)
                        if process.poll() == 0:
                            print('\rFinished{}'.format(pad * (statlen + 3)))
                            break
                    where = output.tell()
                    lines = output.read().decode('UTF-8')
                    if not lines:
                        time.sleep(0.1)
                        output.seek(where)
                    elif 'fps' in lines:
                        ln = lines.split('fps')[-1].strip().rstrip('%')
                        try:
                            pcomp = float(ln)
                        except ValueError:
                            pcomp = 0
                        # python 2 div
                        stat = int((float(pcomp) / float(100)) * statlen)
                        # python 3 div
                        # stat = int((int(pcomp) / 100) * statlen)
                        padlen = statlen - stat
                        status = "|{:6.2f}%|".format(pcomp)
                        statusbar = '|{}{}|'.format(statchar * stat,
                                                    pad * padlen
                                                    )
                        status = '\r{}{}'.format(status, statusbar)
                        print(status, end="")
                        # Replace with flush=True in print function for python 3
                        sys.stdout.flush()

        def subtitle_setup():
            """Configure subtitle encoding input and metadata lists"""
            # move args to self.arg | add self.map_count to encoder
            file_name = (self.input_file.split('/')[-1].split('.')[0]
                         .rsplit('.')[0]
                         )
            subtitle_files = []
            subtitle_count = 0
            self.subtitle_input = []
            self.subtitle_metadata = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file_match in files:
                    if (file_match.startswith(file_name)
                            and file_match.endswith('.srt')):
                        if ('608-cc1' in file_match
                                or '708-service-01' in file_match):
                            subtitle_files.append(
                                str(os.path.join(root, file_match)))

                if subtitle_files:
                    for subtitle_file in subtitle_files:
                        self.map_count = self.map_count + 1
                        subtitle_lang = subtitle_file.split('.')[-2]
                        self.subtitle_input.extend(['-i', subtitle_file])
                        self.subtitle_metadata.extend(
                            ['-map', str(self.map_count),
                             '-metadata:s:s:{}'.format(subtitle_count),
                             'language={}'.format(subtitle_lang)
                             ])
                        subtitle_count = subtitle_count + 1
                    fileformat = self.settings.file.fileformat
                    if fileformat == 'mkv':
                        self.subtitle_input.extend(['-c:s', 'srt'])
                    elif fileformat == 'mp4':
                        self.subtitle_input.extend(['-c:s', 'mov_text'])

        def run_encode(command, avinfo):
            """ Run ffmpeg command with status output"""
            # Length of progress bar
            statlen = 10
            # Character used for progress bar
            # Use chr() in python 3
            statchar = unichr(9619).encode('UTF-8')
            # Character used to pad progress bar
            pad = ' '

            frame_rate = avinfo.video.frame_rate
            duration = float(avinfo.duration)
            total_frames = duration * frame_rate

            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen(command, stdout=output,
                                           stderr=output,
                                           universal_newlines=True
                                           )

                while True:
                    if process.poll() is not None:
                        if process.poll() != 0:
                            output.seek(0)
                            logging.error((output.read().decode('UTF-8')))
                            # print(output.read().decode('UTF-8'))
                            sys.exit(1)
                        if process.poll() == 0:
                            print('\rFinished{}'.format(pad * (statlen + 3)))
                            break
                    where = output.tell()
                    lines = output.read().decode('UTF-8')
                    if not lines:
                        time.sleep(0.1)
                        output.seek(where)
                    elif lines.startswith('frame='):
                        ln = ' '.join(lines.split()).replace('= ', '=').split(
                            ' ')
                        for item in ln:
                            if item.startswith('frame='):
                                framenum = int(item.replace('frame=', ''))
                                # get fps to possibly implement into status
                                # if item.startswith('fps='):
                                # fps = float(item.replace('fps=', ''))
                        if int(framenum) == 0:
                            pcomp = 0
                        else:
                            # python 2 div
                            pcomp = 100 * (float(framenum)
                                           / float(total_frames)
                                           )
                            # python 3 div
                            # pcomp = 100 * (framenum / total_frames)
                        # python 2 div
                        stat = int((float(pcomp) / float(100)) * statlen)
                        # python 3 div
                        # stat = int((int(pcomp) / 100) * statlen)
                        padlen = statlen - stat
                        status = "|{:6.2f}%|".format(pcomp)
                        statusbar = '|{}{}|'.format(statchar * stat,
                                                    pad * padlen)
                        status = '\r{}{}'.format(status, statusbar)
                        print(status, end="")
                        # Replace with flush=True in print function for python 3
                        sys.stdout.flush()

        def standard_transcode(input_file=self.input_file,
                               output_file=self.output_file):
            """Run transcode with optional metadata and subtitles"""
            base_command = [self.ffmpeg, '-y', '-i', input_file]
            if self.metadata_file:
                base_command.extend(['-i', self.metadata_file])
            if self.settings.file.includesub and self.subtitle_input:
                base_command.extend(self.subtitle_input)
            base_command.extend(self.video_config)
            base_command.extend(self.audio_config)
            base_command.extend(['-map_metadata', '1'])
            if self.settings.file.includesub and self.subtitle_metadata:
                base_command.extend(self.subtitle_metadata)
            base_command.append('{}.{}'.format(output_file,
                                               self.settings.file.fileformat
                                               )
                                )
            run_encode(base_command, self.av_info)

        def no_transcode_cut(output_file=self.output_file):
            """Cut commercials without transcoding using FFmpeg -segment"""
            # ?need to add -a53cc 1 for closed caption support?
            cut_command = [self.ffmpeg, '-ignore_unknown', '-i',
                           self.input_file,
                           '-y', '-copyts', '-start_at_zero', '-c', 'copy',
                           '-map', '0'
                           ]
            for streams, stream in self.av_info.audio.items():
                if stream.channels == '0':
                    cut_command.extend(['-map', '-0:{}'.format(stream.index)])
            cut_list = None
            cut_start = 0
            if self.metadata.cutlists.cut_list:
                cut_list = self.metadata.cutlists.cut_list
            if not self.metadata.cutlists.cut_list:
                if self.metadata.cutlists.skip_list:
                    if self.settings.file.usecommflag:
                        cut_list = self.metadata.cutlists.skip_list
            if not cut_list:
                logging.error('No cut-list found')
                sys.exit(1)
            cut_list = [mark for cuts in cut_list for mark in cuts]
            if cut_list[0] == 0:
                cut_start = 1
                cut_list.pop(0)
            if cut_list[-1] == 9999999:
                cut_list.pop(-1)
            cut_list = ','.join(str(i) for i in cut_list)
            cut_command.extend(['-f', 'ssegment', '-segment_frames', cut_list,
                                '{}cut%03d.ts'.format(self.temp_dir)
                                ]
                               )
            run_encode(cut_command, self.av_info)
            logging.info('segmenting video finished')
            # Join segment files in temp_dir.
            #  using cut_start to determine start/step of the files to be joined
            file_list = []
            # Get list of segment files
            for root, dirs, files in os.walk(self.temp_dir):
                for File in files:
                    if (File.endswith('.ts') and
                            File.startswith('cut')):
                        if os.path.isfile(os.path.join(root, File)):
                            file_list.append(os.path.join(root, File))
            # Set list of files to be joined
            join_list = file_list[cut_start::2]
            concat_string = ','.join(join_list).replace(',', '|')
            join_command = [self.ffmpeg, '-y', '-i',
                            'concat:{}'.format(concat_string),
                            '-map', '0', '-c', 'copy', '-f', 'mpegts',
                            '{}.{}'.format(output_file, 'ts')
                            ]
            duration_list = []
            frame_rate_list = []
            video_codec_list = []
            for files in file_list:
                file_avinfo = AVInfo(files)
                # get file duration
                duration_list.append(file_avinfo.duration)
                # Get file reference frame rate
                frame_rate_list.append(file_avinfo.video.frame_rate)
                # Get file video codec
                video_codec_list.append(file_avinfo.video.codec_name)
            # Duration of joined files
            duration = sum(duration_list)
            # Check that all files reference frame-rate are equal
            rfr_match = all(
                frame_rate_list[0] == item for item in frame_rate_list)
            if len(frame_rate_list) == 0 or not rfr_match:
                raise ValueError('Incorrect or missing reference frame rate')
            # check if all files video codec match
            codec_match = all(video_codec_list[0] == item
                              for item in video_codec_list
                              )
            if not codec_match:
                raise ValueError('Not all video codecs match')

            class AVJoin:
                """ status update Replacement object for AVInfo  provides
                self.duration and self.video.r_frame_rate for encode()"""

                def __init__(self, duration, frame_rate):
                    self.duration = duration
                    self.video = DictToNamespace({'frame_rate': frame_rate})

            join_info = AVJoin(duration, frame_rate_list[0])
            run_encode(join_command, join_info)
            logging.info('Finished joining segments')
            # print(subprocess.list2cmdline(join_command))

        # Setup encoding parameters and create metadata file
        video_setup()
        audio_setup()
        metadata_setup()

        if self.settings.file.commethod == 'chapters':
            if self.settings.file.includesub:
                logging.info('Start extracting Closed Captions')
                extract_closed_captions(self.temp_file, self.temp_dir)
                logging.info('Finished extracting Closed Captions')
                subtitle_setup()
            logging.info('Start encoding')
            standard_transcode()
            self.output_file = '{}.{}'.format(self.output_file,
                                              self.settings.file.fileformat
                                              )
            logging.info('Finished encoding')
            logging.debug('Output file: {}'.format(self.output_file))
        if self.settings.file.commethod == 'remove':
            logging.info('Start commercial removal')
            no_transcode_cut(output_file=self.temp_file)
            logging.info('Finished commercial removal')
            self.temp_file = '{}.ts'.format(self.temp_file)
            logging.debug('Output file: {}'.format(self.output_file))
            if self.settings.file.includesub:
                logging.info('Start extracting Closed Captions')
                extract_closed_captions(self.temp_file, self.temp_dir)
                logging.info('Finished extracting Closed Captions')
                subtitle_setup()
            logging.info('Start encoding')
            standard_transcode(input_file=self.temp_file)
            self.output_file = '{}.{}'.format(self.output_file,
                                              self.settings.file.fileformat
                                              )
            logging.info('Finished encoding')
            logging.debug('Output file: {}'.format(self.output_file))
        if self.settings.file.commethod == 'only-cut':
            logging.info('Start commercial removal')
            no_transcode_cut(self.output_file)
            self.output_file = '{}.ts'.format(self.output_file)
            logging.info('Finished commercial removal')
            logging.debug('Output file: {}'.format(self.output_file))

        # Cleanup here?
        remove_temp(self.temp_dir)


def run(jobid=None, chanid=None, starttime=None):
    logging.info('Started')
    # Configure chanid and starttime from userjob input
    job = None
    if jobid:
        job = Job(jobid, db=db)
        chanid = job.chanid
        starttime = job.starttime
        logging.debug('chanid={} starttime={}'.format(chanid, starttime))
    if not jobid:
        chanid = chanid
        starttime = starttime
        logging.debug('chanid={} starttime={}'.format(chanid, starttime))
    # Get database recording entry
    rec = Recorded((chanid, starttime), db=db)
    logging.debug('DB recording entry={}'.format(rec))
    # Find and format full input file path
    sg = findfile('/{}'.format(rec.basename), rec.storagegroup, db=db)
    input_file = os.path.join(sg.dirname, rec.basename)

    rec_meta = RecordingToMetadata(rec, allow_search=settings.file.allowsearch)
    file_items = FileSetup(settings, metadata=rec_meta)
    if settings.file.export:
        out_file = '{}{}'.format(settings.file.fallbackdir, file_items.filename)
    if not settings.file.export:
        out_file = input_file.split('.', -1)[0]

    encoder = Encoder(input_file, out_file, settings=settings,
                      metadata=rec_meta
                      )
    # copy file from fallback to export
    if settings.file.export:
        export_dir = '{}{}'.format(settings.file.exportdir,
                                   file_items.directory
                                   )
        if not os.path.isdir(export_dir):
            logging.info('Export directory not found')
            os.makedirs(export_dir)
            logging.info('Export directory created')
        export_item = '{}{}'.format(settings.file.exportdir,
                                    file_items.directory
                                    )
        print(encoder.output_file)
        print(export_item)
    if not settings.file.export:
        export_item = '{}/'.format(os.path.dirname(input_file))
        print(encoder.output_file)
        print(export_item)
        update_recorded(rec, input_file, encoder.input_file)
    export_file(encoder.output_file, export_item)
    logging.info('Finished')
    sys.exit()


def main():
    parser = argparse.ArgumentParser(
        description='MythTV Commercial removal tool.')
    parser.add_argument('--chanid', action='store', type=str, dest='chanid',
                        help='Channel-Id of Recording'
                        )
    parser.add_argument('--starttime', action='store', type=str,
                        dest='starttime',
                        help='Starttime of recording in utc iso format'
                        )
    parser.add_argument('--jobid', action='store', type=int, dest='jobid',
                        help='Database jobid'
                        )
    args = parser.parse_args()
    if args.jobid:
        run(jobid=args.jobid)
        sys.exit(0)
    if args.chanid and args.starttime:
        run(chanid=args.chanid, starttime=args.starttime)
        sys.exit(0)
    else:
        print('chanid and starttime or jobid required')

main()
