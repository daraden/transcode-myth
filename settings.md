# File tab
## Format
* Selects output container format
## Audio language
* Selects the audio language to include in the output file
  * Selecting all will include all valid audio streams
## Commercial method
* Remove cuts commercials and transcodes
* Chapters sets chapters instead of removing commercials while encoding
* Only-cut removes commercials without re-encoding
  * output will be in ts format
## Save copy of original file
* Saves copy of original recording when modifying recording in the database
  * file will be file.ext.old
## Use commercial detection results
* Allows the use of commercial detection results as a cut-list
## Include subtitles
* Convert closed captions to subtitle streams
## Enable export
* enables exporting of recordings
## Fallback directory
* This is the location used for temporary storage of files
  * exported recordings will be here if the hash verification when moving to the export directory fails
## Export directory
* This is the location you want to send your recordings
## Export type
* Selects the file naming scheme for exported files
## Movie an TV directory structure
* none places recordings directly into the export directory
* folders builds a directory tree for recordings
  * Movies: /Movies/title(year)/
    * year only included if recording entry has a year
  * TV: /TV shows/title/season/
## Include episode title in filename
* Adds the episode name to the end of the recordings filename
## Allow search for unknown programs
* Enables internet metadata search for recordings missing a program-id

# HD/SD tabs
see https://trac.ffmpeg.org/wiki/Encode/H.264 for info related to H.264 options
## video codec
* select output video codec
## preset
* sets the H.264 encoding preset
## CRF
* sets the H.264 crf value
## Audio codec
* selects audio codec for the output file
  * copy keeps the original unprocessed audio streams
## Audio bitrate per channel
* Sets the audio bit-rate depending on the number of channels in the source
  * 2 channels(stereo) at 64 would be 128k