#!/usr/bin/env python2
# -*- coding: UTF-8 -*-
from __future__ import print_function
import json
import os
from io import open
import subprocess
import Tkinter as Tk
import ttk


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


def codec_check(ffmpeg):
    """Check for list of encoders enabled in ffmpeg"""
    # Checks ffmpag available encoders
    command = [ffmpeg, '-encoders']
    run = subprocess.check_output(command)
    available_video = []
    available_audio = ['copy']
    video_list = ['libx264', 'libx265']
    audio_list = ['aac', 'libfdk_aac', 'ac3']

    for line in run.rsplit('\n'):
        for video_codec in video_list:
            if video_codec in line and video_codec not in available_video:
                available_video.append(video_codec)
        for audio_codec in audio_list:
            if audio_codec in line and audio_codec not in available_audio:
                available_audio.append(audio_codec)

    return available_video, available_audio


class ConfigSetup:
    """
    Load configuration file in json format. If no configuration file exists
    a defaults dictionary is used to create one
    """
    conf_path = os.path.dirname(__file__)
    config_file = '{}/conf.json'.format(conf_path)

    defaults = {'file': {'fileformat': 'mp4', 'logdir': '/',
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

    def __init__(self):
        # Write default config file if none exists
        self.file = None
        self.video = None
        self.audio = None
        if not os.path.isfile(self.config_file):
            with open(self.config_file, 'wb') as conf_write:
                json.dump(self.defaults, conf_write)
        config = {}
        config_out = {}
        # Set config dict to values in config file
        with open(self.config_file, 'rb') as conf_read:
            config.update(json.load(conf_read))

        if config.keys() == self.defaults.keys():
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
                if config_out[section].keys() != items.keys():
                    invalid = ([item for item in items.keys()
                                if item not in config_out[section].keys()])
                    missing = ([item for item in config_out[section].keys()
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

    def update(self):
        """Update configuration file with new values"""
        def ns_to_dict(dictionary):
            """Convert namespace to nested dict"""
            nsdict = {}
            for k, v in dictionary.items():
                if isinstance(v, dict):
                    nsdict[k] = ns_to_dict(v)
                else:
                    nsdict[k] = v
            return nsdict

        ns_dict = ns_to_dict(self.__dict__)
        new_dict = {}
        for k, v in ns_dict.items():
            if k in self.defaults.keys():
                new_dict.update({k: v})
        with open(self.config_file, 'wb') as conf_write:
            json.dump(new_dict, conf_write)


settings = ConfigSetup()
ffmpeg = program_check('ffmpeg', 'mythffmpeg')

# Lists of named parameters
video_codecs, audio_codecs = codec_check(ffmpeg)
fileformat = ['mp4', 'mkv']
dirformat = ['none', 'folders']
presets = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
           'slow', 'slower', 'veryslow', 'placebo'
           ]
comrem = ['remove', 'chapters', 'only-cut']
exporttype = ['plex', 'kodi']
audiolanguage = ['eng', 'fre', 'ger', 'ita', 'spa', 'all']

root = Tk.Tk()
root.title('Transcode configuration')
root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)

# Exit button items
exit_button = Tk.Button(root, text='EXIT', command=root.destroy)
exit_button.grid(row=1, column=3, columnspan=1, stick='nsew')

note = ttk.Notebook(root)
frame0 = ttk.Frame(note)
note.add(frame0, text='file')
frame1 = ttk.Frame(note)
note.add(frame1, text='hd')
frame2 = ttk.Frame(note)
note.add(frame2, text='sd')


def file_options(frame, insert_row):
    frame.file_frame = Tk.LabelFrame(frame, text='File options')
    # File format items
    frame.file_frame.format_label = Tk.Label(frame.file_frame, text='Format')
    frame.file_frame.format_var = Tk.StringVar()
    frame.file_frame.format_var.set(settings.file['fileformat'])
    frame.file_frame.Format = ttk.Combobox(frame.file_frame, width=5,
                                           textvariable=frame.file_frame.format_var,
                                           values=fileformat
                                           )
    frame.file_frame.format_label.grid(row=0, column=0)
    frame.file_frame.Format.grid(row=0, column=1, stick='e')
    # audio language items
    frame.file_frame.lang_label = Tk.Label(frame.file_frame,
                                           text='Audio language'
                                           )
    frame.file_frame.lang_var = Tk.StringVar()
    frame.file_frame.lang_var.set(settings.audio['language'])
    frame.file_frame.lang = ttk.Combobox(frame.file_frame, width=5,
                                         textvariable=frame.file_frame.lang_var,
                                         values=audiolanguage
                                         )
    frame.file_frame.lang_label.grid(row=1, column=0)
    frame.file_frame.lang.grid(row=1, column=1, stick='e')
    # Commercial removal method
    frame.file_frame.com_label = Tk.Label(frame.file_frame,
                                          text='Commercial method'
                                          )
    frame.file_frame.com_var = Tk.StringVar()
    frame.file_frame.com_var.set(settings.file['commethod'])
    frame.file_frame.com = ttk.Combobox(frame.file_frame, width=8,
                                        textvariable=frame.file_frame.com_var,
                                        values=comrem
                                        )
    frame.file_frame.com_label.grid(row=2, column=0)
    frame.file_frame.com.grid(row=2, column=1, stick='e')
    # save old copy items
    frame.file_frame.save_old_var = Tk.BooleanVar()
    frame.file_frame.save_old_var.set(settings.file['saveold'])
    frame.file_frame.save_old = Tk.Checkbutton(frame.file_frame,
                                               text='save copy of original file',
                                               variable=frame.file_frame.save_old_var,
                                               onvalue=1, offvalue=0
                                               )
    frame.file_frame.save_old.grid(row=3, column=0, columnspan=4)
    # use commercial detection results items
    frame.file_frame.use_commflag_var = Tk.BooleanVar()
    frame.file_frame.use_commflag_var.set(settings.file['usecommflag'])
    frame.file_frame.use_commflag = Tk.Checkbutton(frame.file_frame,
                                                   text='use commercial detection results',
                                                   variable=frame.file_frame.use_commflag_var,
                                                   onvalue=1, offvalue=0
                                                   )
    frame.file_frame.use_commflag.grid(row=4, column=0, columnspan=4)
    # Incluse subtitle items
    frame.file_frame.includesub_var = Tk.BooleanVar()
    frame.file_frame.includesub_var.set(settings.file['includesub'])
    frame.file_frame.includesub = Tk.Checkbutton(frame.file_frame,
                                                 text='Include subtitles',
                                                 variable=frame.file_frame.includesub_var,
                                                 onvalue=1, offvalue=0
                                                 )
    frame.file_frame.includesub.grid(row=5, column=0, columnspan=4)


    frame.file_frame.grid(row=insert_row, column=0, columnspan=4, stick='we')


def export_options(frame, insert_row):
    frame.export_frame = Tk.LabelFrame(frame, text='Export options')
    # Enable export items
    frame.export_frame.enable_export_var = Tk.BooleanVar()
    frame.export_frame.enable_export_var.set(settings.file['export'])
    frame.export_frame.enable_export = Tk.Checkbutton(frame.export_frame,
                                                      text='Enable Export',
                                                      variable=frame.export_frame.enable_export_var,
                                                      onvalue=1, offvalue=0
                                                      )
    frame.export_frame.enable_export.grid(row=0, column=0, columnspan=4)
    # fallback directory items
    frame.export_frame.fallback_label = Tk.Label(frame.export_frame,
                                                 text='Fallback directory'
                                                 )
    frame.export_frame.fallback_var = Tk.StringVar()
    frame.export_frame.fallback_var.set(settings.file['fallbackdir'])
    frame.export_frame.fallback = Tk.Entry(frame.export_frame,
                                           textvariable=frame.export_frame.fallback_var
                                           )
    frame.export_frame.fallback_label.grid(row=1, column=0, columnspan=4)
    frame.export_frame.fallback.grid(row=2, column=0, columnspan=4, stick='ew')
    # export directory items
    frame.export_frame.export_label = Tk.Label(frame.export_frame,
                                               text='Export directory'
                                               )
    frame.export_frame.export_var = Tk.StringVar()
    frame.export_frame.export_var.set(settings.file['exportdir'])
    frame.export_frame.export = Tk.Entry(frame.export_frame,
                                         textvariable=frame.export_frame.export_var
                                         )
    frame.export_frame.export_label.grid(row=3, column=0, columnspan=4)
    frame.export_frame.export.grid(row=4, column=0, columnspan=4, stick='ew')
    # Export type items
    frame.export_frame.exporttype_label = Tk.Label(frame.export_frame,
                                                   text='Export Type'
                                                   )
    frame.export_frame.exporttype_var = Tk.StringVar()
    frame.export_frame.exporttype = ttk.Combobox(frame.export_frame,
                                                 textvariable=frame.export_frame.exporttype_var,
                                                 values=exporttype, width=8
                                                 )
    frame.export_frame.exporttype.set(settings.file['exporttype'])
    frame.export_frame.exporttype_label.grid(row=5, column=0)
    frame.export_frame.exporttype.grid(row=5, column=1, stick='e')
    # movie directory structure items
    frame.export_frame.mvdir_lable = Tk.Label(frame.export_frame,
                                              text='Movie directory structure'
                                              )
    frame.export_frame.mvdir_var = Tk.StringVar()
    frame.export_frame.mvdir = ttk.Combobox(frame.export_frame,
                                            textvariable=frame.export_frame.mvdir_var,
                                            values=dirformat, width=8
                                            )
    frame.export_frame.mvdir_var.set(settings.file['mvdirstruct'])
    frame.export_frame.mvdir_lable.grid(row=6, column=0)
    frame.export_frame.mvdir.grid(row=6, column=1, stick='e')
    # TV directory structure items
    frame.export_frame.tvdir_lable = Tk.Label(frame.export_frame,
                                              text='TV directory structure'
                                              )
    frame.export_frame.tvdir_var = Tk.StringVar()
    frame.export_frame.tvdir = ttk.Combobox(frame.export_frame,
                                            textvariable=frame.export_frame.tvdir_var,
                                            values=dirformat, width=8
                                            )
    frame.export_frame.tvdir_var.set(settings.file['tvdirstruct'])
    frame.export_frame.tvdir_lable.grid(row=7, column=0)
    frame.export_frame.tvdir.grid(row=7, column=1, stick='e')
    # episode title items
    frame.export_frame.episodetitle_var = Tk.BooleanVar()
    frame.export_frame.episodetitle_var.set(settings.file['episodetitle'])
    frame.export_frame.episodetitle = Tk.Checkbutton(frame.export_frame,
                                                     text='Include episode title in filename',
                                                     variable=frame.export_frame.episodetitle_var,
                                                     onvalue=1, offvalue=0
                                                     )
    frame.export_frame.episodetitle.grid(row=8, column=0, columnspan=4)

    frame.export_frame.episodetitle_var = Tk.BooleanVar()
    frame.export_frame.episodetitle_var.set(settings.file['episodetitle'])
    frame.export_frame.episodetitle = Tk.Checkbutton(frame.export_frame,
                                                     text='Include episode title in filename',
                                                     variable=frame.export_frame.episodetitle_var,
                                                     onvalue=1, offvalue=0
                                                     )
    frame.export_frame.episodetitle.grid(row=8, column=0, columnspan=4)

    frame.export_frame.allowsearch_var = Tk.BooleanVar()
    frame.export_frame.allowsearch_var.set(settings.file['allowsearch'])
    frame.export_frame.allowsearch = Tk.Checkbutton(frame.export_frame,
                                                    text='Allow search for unknown programs',
                                                    variable=frame.export_frame.allowsearch_var,
                                                    onvalue=1, offvalue=0
                                                    )
    frame.export_frame.allowsearch.grid(row=9, column=0, columnspan=4)


    frame.export_frame.grid(row=insert_row, column=0, columnspan=4, stick='we')


def av_opts(frame, deff):
    """Build frame for HD or SD variables"""
    # video codec items
    frame.video_codec_label = Tk.Label(frame, text='Video Codec')
    frame.video_codec_var = Tk.StringVar()
    frame.video_codec_var.set(settings.video['codec{}'.format(deff)])

    frame.video_codec = ttk.Combobox(frame, textvariable=frame.video_codec_var,
                                     values=video_codecs, width=10
                                     )
    frame.video_codec_label.grid(row=1, column=0)
    frame.video_codec.grid(row=1, column=1, stick='e')
    # video preset items
    frame.preset_label = Tk.Label(frame, text='preset')
    frame.preset_var = Tk.StringVar()
    frame.preset = ttk.Combobox(frame, textvariable=frame.preset_var,
                                width=10, values=presets
                                )
    frame.preset_label.grid(row=2, column=0)
    frame.preset.grid(row=2, column=1, stick='e')
    frame.preset_var.set(settings.video['preset{}'.format(deff)])
    # CRF items
    frame.crf_label = Tk.Label(frame, text='CRF')
    frame.crf_var = Tk.StringVar()
    frame.crf = Tk.Spinbox(frame, from_=18, to=28, textvariable=frame.crf_var,
                           width=4
                           )
    frame.crf_label.grid(row=3, column=0)
    frame.crf.grid(row=3, column=1, stick='e')
    frame.crf_var.set(settings.video['crf{}'.format(deff)])
    # min/max bitrate still needs to be implameted
    # max bitrate items
    #frame.max_rate_label = Tk.Label(frame, text='video maximum bitrate')
    #frame.max_rate_var = Tk.StringVar()
    #frame.max_rate = Tk.Spinbox(frame, from_=0, to=10000,
    #                            textvariable=frame.max_rate_var, width=6
    #                            )
    #frame.max_rate_label.grid(row=4, column=0)
    #frame.max_rate.grid(row=4, column=1, stick='e')
    #frame.max_rate_var.set(settings.video['maxrate{}'.format(deff)])
    # min bitrate items
    #frame.min_rate_label = Tk.Label(frame, text='video minimum bitrate')
    #frame.min_rate_var = Tk.StringVar()
    #frame.min_rate = Tk.Spinbox(frame, from_=0, to=10000,
    #                            textvariable=frame.min_rate_var, width=6
    #                            )
    #frame.min_rate_label.grid(row=5, column=0)
    #frame.min_rate.grid(row=5, column=1, stick='e')
    #frame.min_rate_var.set(settings.video['minrate{}'.format(deff)])
    # audio codec items
    frame.audio_codec_label = Tk.Label(frame, text='Audio Codec')
    frame.audio_codec_var = Tk.StringVar()
    frame.audio_codec = ttk.Combobox(frame, textvariable=frame.audio_codec_var,
                                     values=audio_codecs, width=10
                                     )
    frame.audio_codec_label.grid(row=6, column=0)
    frame.audio_codec.grid(row=6, column=1, stick='e')
    frame.audio_codec_var.set(settings.audio['codec{}'.format(deff)])
    # audio bitrate items
    frame.bpc_label = Tk.Label(frame, text='Audio bitrate per Channel')
    frame.bpc_var = Tk.StringVar()
    frame.bpc = Tk.Spinbox(frame, from_=32, to=128, textvariable=frame.bpc_var,
                           width=4
                           )
    frame.bpc_label.grid(row=7, column=0)
    frame.bpc.grid(row=7, column=1, stick='e')
    frame.bpc_var.set(settings.audio['bpc{}'.format(deff)])

file_options(frame0, 1)
export_options(frame0, 2)
av_opts(frame1, 'hd')
av_opts(frame2, 'sd')


note.grid(row=0, column=0, columnspan=4)
root.resizable(width=False, height=False)


def config_update():
    """Write new settings to configuration file"""
    settings.file['fileformat'] = frame0.file_frame.format_var.get()
    settings.file['export'] = frame0.export_frame.enable_export_var.get()
    settings.file['exporttype'] = frame0.export_frame.exporttype.get()
    settings.file['exportdir'] = frame0.export_frame.export_var.get()
    settings.file['fallbackdir'] = frame0.export_frame.fallback_var.get()
    settings.file['mvdirstruct'] = frame0.export_frame.mvdir_var.get()
    settings.file['tvdirstruct'] = frame0.export_frame.tvdir_var.get()
    settings.file['episodetitle'] = frame0.export_frame.episodetitle_var.get()
    settings.file['allowsearch'] = frame0.export_frame.allowsearch_var.get()
    settings.file['saveold'] = bool(frame0.file_frame.save_old_var.get())
    settings.file['usecommflag'] = bool(frame0.file_frame.use_commflag_var.get())
    settings.file['commethod'] = frame0.file_frame.com_var.get()
    settings.file['includesub'] = bool(frame0.file_frame.includesub_var.get())
    settings.video['codechd'] = frame1.video_codec_var.get()
    settings.video['codecsd'] = frame2.video_codec_var.get()
    settings.video['presethd'] = frame1.preset_var.get()
    settings.video['presetsd'] = frame2.preset_var.get()
    settings.video['crfhd'] = int(frame1.crf.get())
    settings.video['crfsd'] = int(frame2.crf.get())
    settings.video['maxratehd'] = int(frame1.max_rate.get())
    settings.video['maxratesd'] = int(frame2.max_rate.get())
    settings.video['minratehd'] = int(frame1.min_rate.get())
    settings.video['minratesd'] = int(frame2.min_rate.get())
    settings.audio['language'] = frame0.file_frame.lang_var.get()
    settings.audio['codechd'] = frame1.audio_codec_var.get()
    settings.audio['codecsd'] = frame2.audio_codec_var.get()
    settings.audio['bpchd'] = int(frame1.bpc.get())
    settings.audio['bpcsd'] = int(frame2.bpc.get())
    print('start update')
    settings.update()

# Save button items
save_button = Tk.Button(root, text='Save', command=config_update)
save_button.grid(row=1, column=2, columnspan=1, stick='nsew')


def main():
    root.mainloop()
main()
