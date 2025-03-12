#!/usr/bin/env python3
"""
YouTube Debugger Tool

Questo strumento aiuta a testare e diagnosticare problemi con l'accesso ai contenuti di YouTube,
con particolare focus sul superare eventuali blocchi o limitazioni imposte ai bot.
"""

import os
import asyncio
import logging
import argparse
import random
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

import requests
from bot import (
    get_video_title, 
    get_transcript_from_youtube, 
    download_audio, 
    transcribe_with_whisper_api,
    extract_video_id,
    USER_AGENTS
)

# Configura il logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("youtube_debug.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("youtube_debugger")

# Directory per salvare risultati debug
DEBUG_DIR = Path("debug_results")
DEBUG_DIR.mkdir(exist_ok=True)

def save_debug_info(data: Dict[str, Any], filename: str) -> None:
    """Salva le informazioni di debug in un file JSON."""
    output_path = DEBUG_DIR / filename
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Debug info salvata in: {output_path}")

async def analyze_cookie_file() -> Dict[str, Any]:
    """Analizza il file dei cookie per verificarne la validità e le caratteristiche."""
    cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    result = {
        "has_cookie_file": os.path.isfile(cookie_file),
        "cookie_path": cookie_file,
        "file_size_bytes": 0,
        "last_modified": None,
        "cookie_domains": [],
        "youtube_cookies_count": 0,
        "important_cookies": {
            "SID": False,
            "HSID": False,
            "SSID": False,
            "APISID": False,
            "SAPISID": False,
            "LOGIN_INFO": False,
            "__Secure-1PSID": False,
            "__Secure-3PSID": False,
            "VISITOR_INFO1_LIVE": False
        },
        "appears_valid": False
    }
    
    if result["has_cookie_file"]:
        try:
            file_stat = os.stat(cookie_file)
            result["file_size_bytes"] = file_stat.st_size
            result["last_modified"] = time.ctime(file_stat.st_mtime)
            
            # Analizza i cookie
            youtube_domains = ['youtube.com', '.youtube.com', 'www.youtube.com']
            
            with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Verifica se il file ha il formato corretto
                if "#HttpOnly_" in content or ".youtube.com" in content:
                    result["appears_valid"] = True
                
                # Cerca domini YouTube
                for domain in youtube_domains:
                    if domain in content:
                        if domain not in result["cookie_domains"]:
                            result["cookie_domains"].append(domain)
                
                # Conta i cookie YouTube e verifica i cookie importanti
                for line in content.split('\n'):
                    if any(domain in line for domain in youtube_domains):
                        result["youtube_cookies_count"] += 1
                        
                        # Verifica cookie importanti
                        for key in result["important_cookies"].keys():
                            if f"{key}\t" in line:
                                result["important_cookies"][key] = True
            
            # Valutazione finale
            critical_cookies = ["SID", "HSID", "LOGIN_INFO", "__Secure-1PSID"]
            result["has_critical_cookies"] = any(result["important_cookies"][k] for k in critical_cookies)
            
        except Exception as e:
            logger.error(f"Errore nell'analisi del file cookie: {e}")
            result["error"] = str(e)
    
    return result

async def test_user_agents(video_id: str) -> Dict[str, bool]:
    """Testa diversi user agent per vedere quali hanno successo."""
    results = {}
    
    for agent in USER_AGENTS:
        logger.info(f"Testing User-Agent: {agent}")
        headers = {'User-Agent': agent}
        
        # Test standard YouTube page
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            success = response.status_code == 200 and "videoDetails" in response.text
            results[agent] = success
            logger.info(f"User-Agent {agent}: {'SUCCESS' if success else 'FAILED'}")
        except Exception as e:
            logger.error(f"Error testing User-Agent {agent}: {e}")
            results[agent] = False
        
        # Aggiungi un ritardo casuale per evitare il rate limiting
        await asyncio.sleep(random.uniform(1.5, 3.0))
    
    return results

async def test_with_cookies(video_id: str) -> Dict[str, Any]:
    """Testa se i cookie migliorano l'accesso."""
    cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    has_cookies = os.path.isfile(cookie_file)
    
    result = {
        "has_cookie_file": has_cookies,
        "cookie_path": cookie_file,
        "cookie_analysis": await analyze_cookie_file(),
        "video_title_test": None,
        "transcript_test": None,
        "download_test": None
    }
    
    if has_cookies:
        logger.info(f"Testing with cookie file: {cookie_file}")
        try:
            # Test recupero titolo
            title = get_video_title(video_id)
            result["video_title_test"] = {
                "success": bool(title and title != f"video_{video_id}"),
                "title": title
            }
            
            # Breve pausa
            await asyncio.sleep(1.5)
            
            # Test recupero trascrizione
            transcript = await get_transcript_from_youtube(video_id)
            result["transcript_test"] = {
                "success": bool(transcript),
                "length": len(transcript) if transcript else 0,
                "excerpt": transcript[:200] if transcript else None
            }
            
            # Breve pausa
            await asyncio.sleep(1.5)
            
            # Test download audio
            audio_file = await download_audio(video_id)
            result["download_test"] = {
                "success": bool(audio_file),
                "file_path": str(audio_file) if audio_file else None
            }
            
        except Exception as e:
            logger.error(f"Error during cookie testing: {e}")
            result["error"] = str(e)
    else:
        logger.warning("No cookie file found. Tests skipped.")
    
    return result

async def test_proxy_settings(video_id: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    """Testa l'accesso tramite proxy."""
    if not proxy:
        logger.info("No proxy specified, skipping proxy test")
        return {"proxy_test": "skipped"}
    
    result = {"proxy": proxy, "tests": {}}
    
    try:
        # Test base con richiesta semplice
        logger.info(f"Testing with proxy: {proxy}")
        proxies = {
            "http": proxy,
            "https": proxy
        }
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        agent = random.choice(USER_AGENTS)
        headers = {'User-Agent': agent}
        
        try:
            response = requests.get(url, headers=headers, proxies=proxies, timeout=15)
            result["tests"]["basic_request"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "response_size": len(response.text),
                "user_agent": agent
            }
        except Exception as e:
            logger.error(f"Proxy request failed: {e}")
            result["tests"]["basic_request"] = {
                "success": False,
                "error": str(e)
            }
    
    except Exception as e:
        logger.error(f"Error during proxy testing: {e}")
        result["error"] = str(e)
    
    return result

async def test_ip_rotation(video_id: str, attempts: int = 3) -> None:
    """Testa la rotazione degli indirizzi IP con delay tra i tentativi."""
    logger.info(f"Testing IP rotation with {attempts} attempts")
    
    results = {"attempts": []}
    
    for i in range(attempts):
        logger.info(f"Attempt {i+1}/{attempts}")
        
        # Usa un User-Agent casuale
        agent = random.choice(USER_AGENTS)
        headers = {'User-Agent': agent}
        
        try:
            # Controlla il nostro IP pubblico corrente
            ip_response = requests.get("https://api.ipify.org?format=json", headers=headers, timeout=10)
            ip_info = ip_response.json() if ip_response.status_code == 200 else {"error": "Failed to get IP"}
            
            # Prova ad accedere a YouTube
            url = f"https://www.youtube.com/watch?v={video_id}"
            yt_response = requests.get(url, headers=headers, timeout=10)
            
            attempt_result = {
                "attempt_number": i+1,
                "timestamp": time.time(),
                "ip_info": ip_info,
                "user_agent": agent,
                "youtube_response": {
                    "status_code": yt_response.status_code,
                    "success": yt_response.status_code == 200 and "videoDetails" in yt_response.text
                }
            }
            
            results["attempts"].append(attempt_result)
            
            logger.info(f"Attempt {i+1} - IP: {ip_info.get('ip', 'unknown')} - Success: {attempt_result['youtube_response']['success']}")
            
            # Attendi un periodo casuale prima del prossimo tentativo
            if i < attempts - 1:
                wait_time = random.uniform(30, 60)
                logger.info(f"Waiting {wait_time:.2f} seconds before next attempt...")
                await asyncio.sleep(wait_time)
                
        except Exception as e:
            logger.error(f"Error during IP rotation test attempt {i+1}: {e}")
            results["attempts"].append({
                "attempt_number": i+1,
                "timestamp": time.time(),
                "error": str(e)
            })
            await asyncio.sleep(10)  # Breve attesa in caso di errore
    
    # Salva i risultati
    timestamp = int(time.time())
    filename = f"ip_rotation_{video_id}_{timestamp}.json"
    save_debug_info(results, filename)
    
    logger.info(f"IP rotation test completed, results saved to {DEBUG_DIR / filename}")

def print_debug_summary(results_file: str) -> None:
    """Mostra un riepilogo dei risultati di debug in formato human-friendly."""
    try:
        with open(results_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print("\n" + "="*80)
        print(f"📊 RIEPILOGO DEBUG PER VIDEO ID: {data.get('video_id', 'N/A')}")
        print("="*80)
        
        # Riepilogo User Agents
        ua_results = data.get('test_results', {}).get('user_agents', {})
        successful_ua = [ua for ua, success in ua_results.items() if success]
        print(f"\n🌐 USER AGENTS: {len(successful_ua)}/{len(ua_results)} funzionanti")
        
        # Analisi Cookie
        cookie_results = data.get('test_results', {}).get('cookies', {})
        cookie_analysis = cookie_results.get('cookie_analysis', {})
        print("\n🍪 ANALISI COOKIE:")
        if cookie_results.get('has_cookie_file'):
            print(f"  ✓ File cookie trovato: {cookie_results.get('cookie_path')}")
            print(f"  ✓ Dimensione: {cookie_analysis.get('file_size_bytes', 0)/1024:.1f}KB")
            print(f"  ✓ Ultima modifica: {cookie_analysis.get('last_modified', 'N/A')}")
            print(f"  ✓ Cookie YouTube: {cookie_analysis.get('youtube_cookies_count', 0)}")
            
            # Cookie importanti
            important_cookies = cookie_analysis.get('important_cookies', {})
            present_cookies = [k for k, v in important_cookies.items() if v]
            missing_cookies = [k for k, v in important_cookies.items() if not v]
            print(f"  ✓ Cookie importanti presenti: {', '.join(present_cookies) if present_cookies else 'nessuno'}")
            print(f"  ✓ Cookie importanti mancanti: {', '.join(missing_cookies) if missing_cookies else 'nessuno'}")
            
            if cookie_analysis.get('has_critical_cookies'):
                print("  ✅ Hai i cookie critici necessari")
            else:
                print("  ❌ Mancano cookie critici - prova a rigenerare il file cookies.txt")
        else:
            print("  ❌ File cookie non trovato")
        
        # Risultati dei test
        print("\n📋 RISULTATI DEI TEST:")
        if cookie_results.get('video_title_test', {}).get('success'):
            print(f"  ✅ Titolo: recuperato con successo")
        else:
            print(f"  ❌ Titolo: recupero fallito")
            
        if cookie_results.get('transcript_test', {}).get('success'):
            print(f"  ✅ Trascrizione: recuperata con successo ({cookie_results.get('transcript_test', {}).get('length', 0)} caratteri)")
        else:
            print(f"  ❌ Trascrizione: recupero fallito")
            
        if cookie_results.get('download_test', {}).get('success'):
            print(f"  ✅ Download audio: riuscito")
        else:
            print(f"  ❌ Download audio: fallito")
        
        # Pipeline completa
        pipeline = data.get('test_results', {}).get('pipeline', {})
        print("\n🔄 PIPELINE COMPLETA:")
        if pipeline.get('transcript_available'):
            print("  ✅ Trascrizione disponibile direttamente da YouTube")
            print("  ℹ️ Il download dell'audio NON è necessario per questo video")
        elif pipeline.get('audio_download'):
            print("  ❌ Trascrizione non disponibile da YouTube")
            print("  ✅ Download audio riuscito")
            if pipeline.get('whisper_transcript'):
                print("  ✅ Trascrizione con Whisper riuscita")
            else:
                print("  ❌ Trascrizione con Whisper fallita")
        else:
            print("  ❌ Trascrizione non disponibile da YouTube")
            print("  ❌ Download audio fallito")
            print("  ⚠️ Non è possibile ottenere la trascrizione per questo video")
        
        # Conclusione
        print("\n📝 CONCLUSIONE:")
        if pipeline.get('transcript_available'):
            print("  ✅ Il bot può trascrivere e riassumere questo video")
            print("  ✅ Non è necessario il download dell'audio")
        elif pipeline.get('whisper_transcript'):
            print("  ✅ Il bot può trascrivere e riassumere questo video tramite Whisper")
        else:
            print("  ❌ Il bot non può elaborare questo video")
        
        print("\n⏱️ Durata del test: {:.2f} secondi".format(data.get('test_duration_seconds', 0)))
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"Errore nella visualizzazione del riepilogo: {e}")

async def comprehensive_test(video_id: str, proxy: Optional[str] = None) -> None:
    """Esegue un test completo di tutte le funzionalità."""
    start_time = time.time()
    
    logger.info(f"Starting comprehensive test for video ID: {video_id}")
    
    all_results = {
        "video_id": video_id,
        "timestamp": time.time(),
        "test_results": {}
    }
    
    # 1. Test dei diversi User-Agent
    logger.info("Testing different User-Agents...")
    ua_results = await test_user_agents(video_id)
    all_results["test_results"]["user_agents"] = ua_results
    
    # 2. Test con i cookie
    logger.info("Testing with cookies...")
    cookie_results = await test_with_cookies(video_id)
    all_results["test_results"]["cookies"] = cookie_results
    
    # 3. Test con proxy (se specificato)
    if proxy:
        logger.info(f"Testing with proxy: {proxy}")
        proxy_results = await test_proxy_settings(video_id, proxy)
        all_results["test_results"]["proxy"] = proxy_results
    
    # 4. Test dell'intera pipeline
    logger.info("Testing complete pipeline...")
    try:
        # Ottieni titolo
        title = get_video_title(video_id)
        all_results["test_results"]["pipeline"] = {"title": title}
        
        # Ottieni trascrizione
        transcript = await get_transcript_from_youtube(video_id)
        all_results["test_results"]["pipeline"]["transcript_available"] = bool(transcript)
        
        if not transcript:
            # Se la trascrizione non è disponibile, prova a scaricare l'audio e trascrivere
            audio_file = await download_audio(video_id)
            all_results["test_results"]["pipeline"]["audio_download"] = bool(audio_file)
            
            if audio_file:
                whisper_transcript = await transcribe_with_whisper_api(audio_file)
                all_results["test_results"]["pipeline"]["whisper_transcript"] = bool(whisper_transcript)
    except Exception as e:
        logger.error(f"Pipeline test failed: {e}")
        all_results["test_results"]["pipeline"] = {"error": str(e)}
    
    # Calcola e aggiungi la durata totale del test
    end_time = time.time()
    all_results["test_duration_seconds"] = end_time - start_time
    
    # Salva i risultati
    timestamp = int(time.time())
    filename = f"debug_{video_id}_{timestamp}.json"
    save_debug_info(all_results, filename)
    
    logger.info(f"Comprehensive test completed in {all_results['test_duration_seconds']:.2f} seconds")
    logger.info(f"Results saved to {DEBUG_DIR / filename}")
    
    # Mostra il riepilogo
    results_file = str(DEBUG_DIR / filename)
    print_debug_summary(results_file)

async def main():
    """Funzione principale."""
    parser = get_parser()
    args = parser.parse_args()
    
    # Gestione URL/ID video
    video_id = args.url
    if "youtube.com" in args.url or "youtu.be" in args.url:
        video_id = extract_video_id(args.url)
        if not video_id:
            logger.error(f"Impossibile estrarre l'ID del video da: {args.url}")
            return
    
    logger.info(f"Starting debug session for video ID: {video_id}")
    
    if args.test == "all":
        await comprehensive_test(video_id, args.proxy)
    elif args.test == "useragent":
        results = await test_user_agents(video_id)
        save_debug_info({"video_id": video_id, "user_agent_tests": results}, f"useragent_{video_id}.json")
    elif args.test == "cookies":
        results = await test_with_cookies(video_id)
        save_debug_info({"video_id": video_id, "cookie_tests": results}, f"cookies_{video_id}.json")
        
        # Mostra un riepilogo dell'analisi dei cookie
        cookie_analysis = results.get("cookie_analysis", {})
        print("\n🍪 ANALISI DEI COOKIE:")
        if results.get("has_cookie_file"):
            print(f"  • File trovato: {results.get('cookie_path')}")
            print(f"  • Dimensione: {cookie_analysis.get('file_size_bytes', 0)/1024:.1f}KB")
            print(f"  • Cookie YouTube: {cookie_analysis.get('youtube_cookies_count', 0)}")
            
            important_cookies = cookie_analysis.get("important_cookies", {})
            present = sum(1 for v in important_cookies.values() if v)
            print(f"  • Cookie critici: {present}/{len(important_cookies)}")
            
            if cookie_analysis.get("has_critical_cookies"):
                print("  ✅ I cookie sembrano validi per operazioni base")
            else:
                print("  ⚠️ Mancano cookie critici - alcune operazioni potrebbero fallire")
                
            missing = [k for k, v in important_cookies.items() if not v]
            if missing:
                print(f"  ⚠️ Cookie mancanti: {', '.join(missing)}")
        else:
            print("  ❌ File cookie non trovato")
            
    elif args.test == "pipeline":
        try:
            logger.info("Testing title retrieval...")
            title = get_video_title(video_id)
            logger.info(f"Title: {title}")
            
            logger.info("Testing transcript retrieval...")
            transcript = await get_transcript_from_youtube(video_id)
            if transcript:
                logger.info(f"Transcript found! Length: {len(transcript)} chars")
                logger.info(f"Sample: {transcript[:200]}...")
            else:
                logger.info("No transcript available from YouTube")
                
                logger.info("Testing audio download...")
                audio_file = await download_audio(video_id)
                if audio_file:
                    logger.info(f"Audio downloaded: {audio_file}")
                    
                    logger.info("Testing Whisper transcription...")
                    whisper_transcript = await transcribe_with_whisper_api(audio_file)
                    if whisper_transcript:
                        logger.info(f"Whisper transcript created! Length: {len(whisper_transcript)} chars")
                        logger.info(f"Sample: {whisper_transcript[:200]}...")
                    else:
                        logger.info("Whisper transcription failed")
                else:
                    logger.info("Audio download failed")
            
            save_debug_info({
                "video_id": video_id,
                "title": title,
                "transcript_available": bool(transcript),
                "transcript_length": len(transcript) if transcript else 0,
                "transcript_sample": transcript[:200] if transcript else None
            }, f"pipeline_{video_id}.json")
            
        except Exception as e:
            logger.error(f"Pipeline test error: {e}")
    elif args.test == "iprotation":
        await test_ip_rotation(video_id, args.attempts)
    elif args.test == "cookieanalysis":
        # Test dedicato all'analisi dei cookie
        logger.info("Analyzing cookie file...")
        cookie_analysis = await analyze_cookie_file()
        save_debug_info({"cookie_analysis": cookie_analysis}, "cookie_analysis.json")
        
        print("\n🍪 ANALISI DETTAGLIATA DEI COOKIE:")
        if cookie_analysis.get("has_cookie_file"):
            print(f"  • File trovato: {cookie_analysis.get('cookie_path')}")
            print(f"  • Dimensione: {cookie_analysis.get('file_size_bytes', 0)/1024:.1f}KB")
            print(f"  • Ultima modifica: {cookie_analysis.get('last_modified')}")
            print(f"  • Domini YouTube: {', '.join(cookie_analysis.get('cookie_domains', []))}")
            print(f"  • Numero cookie YouTube: {cookie_analysis.get('youtube_cookies_count', 0)}")
            
            print("\n  COOKIE CRITICI:")
            for cookie, present in cookie_analysis.get("important_cookies", {}).items():
                status = "✅ Presente" if present else "❌ Mancante"
                print(f"  • {cookie}: {status}")
            
            if cookie_analysis.get("has_critical_cookies"):
                print("\n  ✅ I cookie sembrano validi per le operazioni di base")
                print("  ⚠️ Tuttavia, YouTube potrebbe comunque bloccare il download dell'audio")
            else:
                print("\n  ⚠️ Mancano cookie critici - rigenerare il file cookies.txt")
                print("  💡 Assicurati di essere loggato su YouTube quando esporti i cookie")
        else:
            print("  ❌ File cookie non trovato")
    
    logger.info("Debug session completed")

def get_parser():
    """Crea il parser degli argomenti da riga di comando."""
    parser = argparse.ArgumentParser(description="YouTube Debugging Tool")
    parser.add_argument("url", help="YouTube URL o video ID da testare")
    parser.add_argument(
        "--test", choices=["all", "useragent", "cookies", "pipeline", "iprotation", "cookieanalysis"],
        default="all", help="Tipo di test da eseguire"
    )
    parser.add_argument("--proxy", help="Proxy URL da utilizzare (format: http://user:pass@host:port)")
    parser.add_argument("--attempts", type=int, default=3, help="Numero di tentativi per i test di rotazione IP")
    return parser

if __name__ == "__main__":
    asyncio.run(main())