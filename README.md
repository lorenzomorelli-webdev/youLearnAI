# YouLearn - YouTube Video Transcription and Summarization Tool

YouLearn is a Python application that automatically transcribes YouTube videos and generates AI-powered summaries of their content.

## Features

- Extract subtitles directly from YouTube videos when available
- Download and transcribe audio using Whisper when subtitles are not available
- Generate AI-powered summaries of video content (optional)
- Save transcriptions and summaries as text files

## How It Works

1. The user provides a YouTube video URL
2. The tool attempts to extract subtitles using `youtube-transcript-api`
3. If subtitles are not available, it downloads the audio and transcribes it using OpenAI's Whisper
4. The transcription is saved to a text file
5. (Optional) The transcription is sent to GPT-4 for summarization

## Requirements

- Python 3.8+
- FFmpeg (must be installed on your system)
- OpenAI API key (optional, for GPT summarization)

## Installation

1. Clone this repository:

```bash
git clone https://github.com/yourusername/youlearn.git
cd youlearn
```

2. Install the required Python packages:

```bash
pip install -r requirements.txt
```

3. Make sure FFmpeg is installed on your system:

   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt install ffmpeg` or equivalent

4. (Optional) Create a `.env` file in the project directory with your OpenAI API key:

```
OPENAI_API_KEY=your_api_key_here
```

## Usage

```bash
python youlearn.py https://www.youtube.com/watch?v=VIDEO_ID [--summarize]
```

Options:

- `--summarize`: Generate a summary using OpenAI's GPT (requires API key)

Example:

```bash
python youlearn.py https://www.youtube.com/watch?v=dQw4w9WgXcQ --summarize
```

The output files will be saved in the `output` directory.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [OpenAI API](https://openai.com/api/)
