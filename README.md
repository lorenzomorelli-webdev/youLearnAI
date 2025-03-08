# YouLearn

YouLearn is a Python tool that transcribes YouTube videos and generates AI-powered summaries using either OpenAI's GPT or Deepseek's models.

## Features

- Extract transcripts from YouTube videos
- Automatic transcription using Whisper when YouTube subtitles are not available
- Generate summaries using either OpenAI's GPT or Deepseek's AI models
- Support for both standard YouTube videos and Shorts
- Clean output organization in a dedicated directory

## Prerequisites

- Python 3.7+
- FFmpeg installed and added to PATH
- OpenAI API key and/or Deepseek API key

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd youlearn
```

2. Install the required Python packages:

```bash
pip install -r requirements.txt
```

3. Install FFmpeg:

   - Windows: Download from [FFmpeg official website](https://ffmpeg.org/download.html)
   - Mac: `brew install ffmpeg`
   - Linux: `sudo apt-get install ffmpeg`

4. Create a `.env` file in the project root and add your API keys:

```env
OPENAI_API_KEY=your_openai_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

## Usage

Basic usage:

```bash
python youlearn.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Generate summary with OpenAI (default):

```bash
python youlearn.py "https://www.youtube.com/watch?v=VIDEO_ID" --summarize
```

Generate summary with Deepseek:

```bash
python youlearn.py "https://www.youtube.com/watch?v=VIDEO_ID" --summarize --ai-service deepseek
```

### Command Line Arguments

- `url`: YouTube video URL (required)
- `--summarize`: Generate an AI summary of the transcript
- `--ai-service`: Choose the AI service for summarization (choices: "openai", "deepseek", default: "openai")

## Output

The script creates an `output` directory containing:

- `video_title_transcript.txt`: The video transcript
- `video_title_openai_summary.txt` or `video_title_deepseek_summary.txt`: The AI-generated summary (if requested)

## Notes

- The script will first attempt to get subtitles directly from YouTube
- If no subtitles are available, it will download the audio and use Whisper for transcription
- Summaries are generated using either OpenAI's GPT-3.5-turbo or Deepseek's model
- The script automatically handles video title sanitization for file naming

## Error Handling

- Missing API keys will result in appropriate warning messages
- FFmpeg installation is verified before processing
- Invalid YouTube URLs are detected and reported
- Failed transcriptions or summarizations are handled gracefully

## Contributing

Feel free to open issues or submit pull requests for any improvements.

## License

[Your chosen license]

## Acknowledgments

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [OpenAI API](https://openai.com/api/)
