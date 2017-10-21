# Transcode-Myth

Transcode-Myth is a python based script. Designed to provide transcoding of MythTV Recordings,
commercial removal, and exporting recordings into formats compatible with popular media managers.

### Features
* Supported output formats mp4, mkv and ts(when using the only-cut option)
* Audio language selection
* Remove commercials or set chapters from a cut-list or commercial detection results
* Convert closed captions to embedded subtitle  streams
* Embedded metadata
  * metadata for mkv not spec compliant
* Export with Kodi or Plex compatible filename. including optional episode title.
* Build directory tree for exported recordings
* Sha1 hash verification for transfer to export directory
* Optional internet search for recordings without a program-id
* H.264 crf encoding
* Audio bit-rate configured per channel

## Getting Started

After downloading Transcode-Myth.
simply setup a MythTV user-job as /path to script/Transcode.py --jobid %JOBID%.
Then run transcode_config.py to use the configuration GUI to customize settings.
For infiormation on settings see [settings.md](settings.md)
### Prerequisites

A fully working MythTV install including the MythTV python bindings.

The python Tkinter module is required For the configuration GUI

optional external FFmpeg or ccextractor installation

## License

This project is licensed under the GNU GENERAL PUBLIC LICENSE V3 - see the [LICENSE](LICENSE) file for details

## Acknowledgments
[MythTV](https://www.mythtv.org/)

[FFmpeg](https://ffmpeg.org/) 