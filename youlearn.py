#!/usr/bin/env python3
"""
YouLearn - YouTube Video Transcription and Summarization Tool

This script transcribes YouTube videos and optionally generates
summaries using OpenAI's GPT models or Deepseek's models.
"""

import argparse
import os
import sys
import re
import time
from pathlib import Path
import subprocess
import textwrap
from typing import Optional, Literal

import dotenv
import requests
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import yt_dlp
import whisper
from openai import OpenAI
from tqdm import tqdm

# Load environment variables from .env file
dotenv.load_dotenv()

# Set up API keys from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Output directory
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    # Match YouTube URL patterns
    patterns = [
        r'(?:v=|/v/|youtu\.be/|/embed/)([^&?/]+)',  # Standard YT URLs
        r'(?:youtube\.com/shorts/)([^&?/]+)',       # YouTube Shorts
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    print(f"Error: Could not extract video ID from URL: {url}")
    return None

def get_video_title(video_id: str) -> str:
    """Get the title of a YouTube video."""
    # Use yt-dlp to get video info
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('title', f"video_{video_id}")
        except Exception as e:
            print(f"Warning: Could not get video title: {e}")
            return f"video_{video_id}"

def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """Try to get transcript directly from YouTube."""
    try:
        print("Attempting to fetch subtitles from YouTube...")
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to get English transcript first
        try:
            transcript = transcript_list.find_transcript(['en'])
        except NoTranscriptFound:
            # If English not available, use any available transcript
            transcript = transcript_list.find_transcript(['en'])
            
        # Get the transcript text
        transcript_data = transcript.fetch()
        
        # Join all transcript parts
        full_transcript = " ".join([part['text'] for part in transcript_data])
        print("Successfully retrieved subtitles from YouTube.")
        return full_transcript
    
    except (TranscriptsDisabled, NoTranscriptFound):
        print("No subtitles available on YouTube.")
        return None
    except Exception as e:
        print(f"Error retrieving subtitles: {e}")
        return None

def download_audio(video_id: str) -> Optional[str]:
    """Download audio from YouTube video."""
    output_file = f"temp_{video_id}.mp3"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f"temp_{video_id}.%(ext)s",
        'quiet': False,
        'no_warnings': True,
    }
    
    print(f"Downloading audio from video {video_id}...")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        print("Audio download complete.")
        return output_file
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return None

def transcribe_with_whisper(audio_file: str) -> Optional[str]:
    """Transcribe audio using OpenAI's Whisper."""
    try:
        print("Transcribing audio with Whisper (this may take a while)...")
        model = whisper.load_model("base")  # Options: tiny, base, small, medium, large
        result = model.transcribe(audio_file)
        print("Transcription complete.")
        return result["text"]
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None
    finally:
        # Clean up the temporary audio file
        try:
            os.remove(audio_file)
            print(f"Removed temporary file: {audio_file}")
        except Exception as e:
            print(f"Warning: Could not remove temporary file {audio_file}: {e}")

def summarize_with_ai(transcript: str, video_title: str, service: Literal["openai", "deepseek"] = "openai") -> Optional[str]:
    """Generate a summary of the transcript using either OpenAI's GPT or Deepseek."""
    
    # Prepare the prompt
    system_prompt = "You are an expert at summarizing video content. Create a comprehensive summary of the following video transcript."
    user_prompt = f"Title: {video_title}\n\nTranscript:\n{transcript}\n\nPlease provide a detailed summary of this video's content, highlighting the main points, key insights, and important details."
    
    try:
        print(f"Generating summary with {service.upper()} (this may take a while)...")
        
        if service == "openai":
            if not OPENAI_API_KEY:
                print("Error: OpenAI API key not found. Set the OPENAI_API_KEY environment variable.")
                return None
                
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # You can change this to other OpenAI models
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1500,
                temperature=0.5,
            )
            
        elif service == "deepseek":
            if not DEEPSEEK_API_KEY:
                print("Error: Deepseek API key not found. Set the DEEPSEEK_API_KEY environment variable.")
                return None
                
            client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com"
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1500,
                temperature=0.5,
            )
            
        summary = response.choices[0].message.content
        print("Summary generation complete.")
        return summary
        
    except Exception as e:
        print(f"Error generating summary with {service}: {e}")
        return None

def save_to_file(content: str, filename: str) -> None:
    """Save content to a file."""
    file_path = OUTPUT_DIR / filename
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
        print(f"Saved to {file_path}")
    except Exception as e:
        print(f"Error saving to {filename}: {e}")

def sanitize_filename(title: str) -> str:
    """Convert a string to a safe filename."""
    # Replace invalid characters with underscores
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
    # Truncate if too long
    if len(safe_title) > 100:
        safe_title = safe_title[:100]
    return safe_title

def process_video(video_url: str, summarize: bool = False, ai_service: str = "openai") -> None:
    """Main function to process a YouTube video."""
    # Extract video ID
    video_id = extract_video_id(video_url)
    if not video_id:
        return
    
    # Get video title
    video_title = get_video_title(video_id)
    safe_title = sanitize_filename(video_title)
    
    print(f"\nProcessing: {video_title}")
    print(f"Video ID: {video_id}")
    
    # Try to get transcript directly from YouTube
    transcript = get_transcript_from_youtube(video_id)
    
    # If no transcript found, download audio and transcribe with Whisper
    if not transcript:
        print("No transcript available through YouTube API.")
        audio_file = download_audio(video_id)
        if audio_file:
            transcript = transcribe_with_whisper(audio_file)
    
    # If we have a transcript, save it and optionally summarize
    if transcript:
        # Save transcript
        transcript_filename = f"{safe_title}_transcript.txt"
        save_to_file(transcript, transcript_filename)
        
        # Generate and save summary if requested
        if summarize:
            if ai_service == "openai" and not OPENAI_API_KEY:
                print("Warning: OpenAI summarization requested but API key not found.")
            elif ai_service == "deepseek" and not DEEPSEEK_API_KEY:
                print("Warning: Deepseek summarization requested but API key not found.")
            else:
                summary = summarize_with_ai(transcript, video_title, ai_service)
                if summary:
                    summary_filename = f"{safe_title}_{ai_service}_summary.txt"
                    save_to_file(summary, summary_filename)
        
        print("\nProcessing complete!")
        print(f"Output files are in the '{OUTPUT_DIR}' directory.")
    else:
        print("Failed to obtain transcript.")

def check_dependencies() -> bool:
    """Check if all required dependencies are installed."""
    # Check for FFmpeg
    try:
        subprocess.run(
            ["ffmpeg", "-version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        return True
    except FileNotFoundError:
        print("Error: FFmpeg not found. Please install FFmpeg and add it to your PATH.")
        print("Download FFmpeg from: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"Error checking for FFmpeg: {e}")
        return False

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Transcribe and summarize YouTube videos",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "url", 
        help="YouTube video URL to process"
    )
    
    parser.add_argument(
        "--summarize", 
        action="store_true",
        help="Generate a summary of the transcript using AI"
    )
    
    parser.add_argument(
        "--ai-service",
        choices=["openai", "deepseek"],
        default="openai",
        help="Choose the AI service for summarization (default: openai)"
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Process the video
    process_video(args.url, args.summarize, args.ai_service)

if __name__ == "__main__":
    main() 