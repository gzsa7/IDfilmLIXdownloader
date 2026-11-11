"""
Helper Class for IDLIX Downloader & IDLIX Player CLI

Update  :   28-11-2025
Author  :   sandroputraa
"""

import os
import random
import re
import json
import m3u8
import shutil
import sys
import zipfile
import requests
import tempfile
import subprocess
import m3u8_To_MP4
import hashlib
from collections import OrderedDict
from io import BytesIO
from PIL import Image

from loguru import logger
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import unquote, urlparse, urljoin
from vtt_to_srt.vtt_to_srt import ConvertFile

from curl_cffi import requests as cffi_requests
from src.CryptoJsAesHelper import CryptoJsAes, dec

# ============================================================
# CENTRALIZED DOMAIN CONFIGURATION MANAGER
# ============================================================
CONFIG_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)
DEFAULT_BASE_URL = "https://z2.idlixku.com/"


def normalize_base_url(url: str) -> str:
    if not url:
        return DEFAULT_BASE_URL
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    if not url.endswith("/"):
        url = url + "/"
    return url


def load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE_PATH):
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "base_url" in data:
                    data["base_url"] = normalize_base_url(data["base_url"])
                    return data
    except Exception as e:
        logger.warning(f"Failed to load config file: {e}")

    return {"base_url": DEFAULT_BASE_URL}


def save_config(base_url: str) -> bool:
    try:
        norm_url = normalize_base_url(base_url)
        config_data = {"base_url": norm_url}
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def get_base_url() -> str:
    return load_config().get("base_url", DEFAULT_BASE_URL)


# ============================================================
# DOMAIN HEALTH CHECK & APPLICATION VALIDATION
# ============================================================
def check_domain_status(base_url: str, timeout: int = 5) -> dict:
    norm_url = normalize_base_url(base_url)
    try:
        parsed = urlparse(norm_url)
        if not parsed.scheme or not parsed.netloc:
            return {"status": False, "code": "INVALID_URL", "message": "Format URL tidak valid"}

        sess = cffi_requests.Session(impersonate="chrome124")
        test_endpoint = urljoin(norm_url, "api/movies")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": norm_url
        }

        resp = sess.get(test_endpoint, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            try:
                json_data = resp.json()
                if isinstance(json_data, dict) and ("data" in json_data or "results" in json_data):
                    return {
                        "status": True,
                        "code": "SUCCESS",
                        "message": "Domain terverifikasi & beroperasi dengan baik",
                        "base_url": norm_url
                    }
                else:
                    return {
                        "status": False,
                        "code": "APPLICATION_INVALID",
                        "message": "Domain dapat diakses tetapi tidak mengembalikan struktur API IDLIX"
                    }
            except Exception:
                return {
                    "status": False,
                    "code": "APPLICATION_INVALID",
                    "message": "Domain dapat diakses tetapi tidak mengembalikan JSON API yang sesuai"
                }
        else:
            return {
                "status": False,
                "code": "HTTP_ERROR",
                "message": f"Server mengembalikan HTTP status {resp.status_code}"
            }

    except cffi_requests.errors.RequestsError as req_err:
        err_str = str(req_err)
        if "timeout" in err_str.lower():
            return {"status": False, "code": "TIMEOUT", "message": "Koneksi ke domain mengalami timeout"}
        return {"status": False, "code": "CONNECTION_ERROR", "message": f"Gagal terhubung ke domain: {err_str}"}
    except Exception as e:
        return {"status": False, "code": "UNKNOWN_ERROR", "message": f"Error pengujian domain: {str(e)}"}


# ============================================================
# BOUNDED POSTER CACHE MANAGER (DISK & LRU MEMORY CACHE)
# ============================================================
class PosterCacheManager:
    """
    Dual-level Poster Cache:
    1. In-Memory LRU Cache with upper bound MAX_MEMORY_CACHE_ITEMS (default 60).
    2. Local Disk Cache stored in .cache/posters/ directory.
    """
    MAX_MEMORY_CACHE_ITEMS = 60

    def __init__(self, cache_dir=None):
        if not cache_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_dir = os.path.join(base_dir, ".cache", "posters")

        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self._memory_cache = OrderedDict()
        import threading
        self._lock = threading.Lock()

    def _url_to_hash(self, url: str) -> str:
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def get_image(self, url: str, target_size=None):
        if not url:
            return None

        url_key = f"{url}_{target_size[0]}x{target_size[1]}" if target_size else url

        # 1. Check In-Memory Cache
        with self._lock:
            if url_key in self._memory_cache:
                self._memory_cache.move_to_end(url_key)
                return self._memory_cache[url_key]

        # 2. Check Disk Cache
        file_hash = self._url_to_hash(url)
        disk_path = os.path.join(self.cache_dir, f"{file_hash}.png")

        img = None
        if os.path.exists(disk_path):
            try:
                img = Image.open(disk_path)
                if target_size:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
            except Exception as e:
                logger.warning(f"Error reading disk cache {disk_path}: {e}")
                img = None

        # 3. Download from HTTP if not in disk cache
        if not img:
            try:
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    raw_img = Image.open(BytesIO(resp.content))
                    raw_img.save(disk_path, format="PNG")
                    if target_size:
                        img = raw_img.resize(target_size, Image.Resampling.LANCZOS)
                    else:
                        img = raw_img
            except Exception as download_err:
                logger.warning(f"Failed downloading poster {url}: {download_err}")
                return None

        # 4. Put into In-Memory LRU Cache
        if img:
            with self._lock:
                self._memory_cache[url_key] = img
                self._memory_cache.move_to_end(url_key)
                if len(self._memory_cache) > self.MAX_MEMORY_CACHE_ITEMS:
                    self._memory_cache.popitem(last=False)

        return img


poster_cache_manager = PosterCacheManager()


class IdlixHelper:
    def __init__(self, base_url=None):
        cfg = load_config()
        self.BASE_WEB_URL = normalize_base_url(base_url or cfg.get("base_url", DEFAULT_BASE_URL))

        # Dynamic static headers (removed hardcoded Host header)
        self.headers = {
            "Connection": "keep-alive",
            "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Windows",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": self.BASE_WEB_URL,
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8"
        }

        self.poster = None
        self.m3u8_url = None
        self.master_m3u8_url = None
        self.video_id = None
        self.video_slug = None
        self.embed_url = None
        self.video_name = None
        self.is_subtitle = None
        self.subtitles_list = []
        self.variant_playlist = None
        self.content_type = "movie"
        self.seasons_list = []
        self.selected_episode = None
        self.download_process = None
        self.download_cancelled = False
        self.download_paused = False
        self.download_output_path = None
        self.download_stream_url = None
        self.stream_cookies = {}  # Cookies dari sesi redeem untuk autentikasi fragment
        self.stream_referer = None  # Referer spesifik CDN stream server
        self.request = cffi_requests.Session(
            impersonate=random.choice(["chrome124", "chrome119", "chrome104"]),
            headers=self.headers,
            debug=False,
        )

    def get_referer(self):
        return self.BASE_WEB_URL

    def get_origin(self):
        return self.BASE_WEB_URL.rstrip('/')

    def reset_download_state(self):
        """Reset all per-movie/per-download state so consecutive downloads
        don't re-use stale URLs or metadata from a previous movie."""
        self.poster = None
        self.m3u8_url = None
        self.master_m3u8_url = None
        self.video_id = None
        self.video_slug = None
        self.embed_url = None
        self.video_name = None
        self.is_subtitle = None
        self.subtitles_list = []
        self.variant_playlist = None
        self.content_type = "movie"
        self.seasons_list = []
        self.selected_episode = None
        self.download_process = None
        self.download_cancelled = False
        self.download_paused = False
        self.download_output_path = None
        self.download_stream_url = None
        self.stream_cookies = {}
        self.stream_referer = None

    def set_active_domain(self, base_url: str):
        self.BASE_WEB_URL = normalize_base_url(base_url)
        self.headers["Referer"] = self.BASE_WEB_URL
        self.request.headers["Referer"] = self.BASE_WEB_URL

    def cancel_download(self):
        self.download_cancelled = True
        if self.download_process and self.download_process.poll() is None:
            try:
                self.download_process.terminate()
                self.download_process.kill()
            except Exception:
                pass
        self.download_process = None
        if self.download_output_path:
            self.cleanup_partial_files(self.download_output_path)
        logger.info("Download cancelled and temporary files cleaned up.")

    def pause_download(self):
        self.download_paused = True
        if self.download_process and self.download_process.poll() is None:
            try:
                self.download_process.terminate()
            except Exception:
                pass
        self.download_process = None
        logger.info("Download paused.")

    def resume_download(self, progress_callback=None):
        self.download_paused = False
        self.download_cancelled = False
        return self.download_with_ytdlp(
            stream_url=self.download_stream_url,
            output_filename=self.download_output_path,
            progress_callback=progress_callback
        )

    @staticmethod
    def cleanup_partial_files(output_path):
        if not output_path:
            return

        dir_name, base_name = os.path.split(output_path)
        if not dir_name or not os.path.exists(dir_name):
            dir_name = os.getcwd()

        base_stem = os.path.splitext(base_name)[0]

        try:
            for file_item in os.listdir(dir_name):
                full_item = os.path.join(dir_name, file_item)
                if not os.path.isfile(full_item):
                    continue

                if (file_item.startswith(base_stem) or file_item.startswith(base_name)) and (
                    file_item.endswith(".part") or file_item.endswith(".ytdl") or
                    ".part-Frag" in file_item or file_item.endswith(".temp") or
                    file_item.endswith(".tmp")
                ):
                    try:
                        os.remove(full_item)
                        logger.info(f"Cleaned up partial download file: {file_item}")
                    except Exception as err:
                        logger.warning(f"Failed to remove partial file {file_item}: {err}")

            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    logger.info(f"Cleaned up target file: {os.path.basename(output_path)}")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error during cleanup of partial files: {e}")

        # Proxy Example
        # self.request.proxies = {
        #    'https': ''
        # }

        # FFMPEG
        if os.name == 'nt':
            for _ in os.environ.get('path').split(';'):
                if 'ffmpeg' in _:
                    logger.info(f'FFMPEG Found: {_}')
                    break
            else:
                if not os.path.exists('ffmpeg-release-essentials.zip'):
                    self.download_ffmpeg()
                logger.warning('FFMPEG not set in PATH, Trying set PATH')
                try:
                    with zipfile.ZipFile('ffmpeg-release-essentials.zip', 'r') as zip_ref:
                        zip_ref.extractall(
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
                        )
                    logger.success('Success Extracting ffmpeg')
                    path = ""
                    for _ in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')):
                        if 'ffmpeg' in _:
                            logger.info(f'Found: {os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")}')
                            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")
                            break
                    else:
                        logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                    subprocess.call(["setx", "PATH", "%PATH%;" + path])
                    logger.success('FFMPEG PATH set successfully, Please restart the program')
                    exit()
                except Exception as e:
                    print(f'Error: {e}')
        else:
            if not shutil.which('ffmpeg'):
                logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                exit()

    @staticmethod
    def download_ffmpeg():
        try:
            logger.info('Downloading ffmpeg')
            content = requests.get(
                url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
                stream=True
            )
            with open("ffmpeg-release-essentials.zip", mode="wb") as file:
                for chunk in content.iter_content(chunk_size=1024):
                    print(
                        '\rDownloading: {} MB of {} MB'.format(
                            round(os.path.getsize('ffmpeg-release-essentials.zip') / 1024 / 1024, 2),
                            round(int(content.headers.get('Content-Length', 0)) / 1024 / 1024, 2)
                        ),
                        end=''
                    )
                    file.write(chunk)
            print()
            logger.success('Downloaded ffmpeg')
        except Exception as e:
            print(f'Error: {e}')

    def get_home(self):
        try:
            request = self.request.get(
                url=self.BASE_WEB_URL + "api/movies",
                timeout=10
            )
            if request.status_code == 200:
                data = request.json().get("data", [])
                tmp_featured = []
                for movie in data:
                    slug = movie.get("slug", "")
                    poster_path = movie.get("posterPath", "")
                    if poster_path and poster_path.startswith("/"):
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    else:
                        poster_url = poster_path

                    release_date = movie.get("releaseDate", "")
                    year = release_date.split("-")[0] if release_date else ""

                    tmp_featured.append({
                        "url": f"{self.BASE_WEB_URL}movie/{slug}",
                        "title": movie.get("title", ""),
                        "year": year,
                        "type": movie.get("contentType", "movie"),
                        "poster": poster_url,
                        "id": movie.get("id"),
                        "slug": slug
                    })
                return {
                    'status': True,
                    'featured_movie': tmp_featured
                }
            else:
                return {
                    'status': False,
                    'message': 'Failed to get home page'
                }
        except Exception as error_get_home:
            return {
                'status': False,
                'message': str(error_get_home)
            }

    def search_movie(self, query):
        if not query or not query.strip():
            return {
                'status': False,
                'message': 'Query is required'
            }
        try:
            request = self.request.get(
                url=f"{self.BASE_WEB_URL}api/search",
                params={"q": query.strip()},
                timeout=10
            )
            if request.status_code == 200:
                results = request.json().get("results", [])
                tmp_movies = []
                for movie in results:
                    slug = movie.get("slug", "")
                    poster_path = movie.get("posterPath", "")
                    if poster_path and poster_path.startswith("/"):
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    else:
                        poster_url = poster_path

                    release_date = movie.get("releaseDate", "")
                    year = release_date.split("-")[0] if release_date else ""

                    tmp_movies.append({
                        "url": f"{self.BASE_WEB_URL}movie/{slug}",
                        "title": movie.get("title", ""),
                        "year": year,
                        "type": movie.get("contentType", "movie"),
                        "poster": poster_url,
                        "id": movie.get("id"),
                        "slug": slug
                    })
                return {
                    'status': True,
                    'featured_movie': tmp_movies
                }
            else:
                return {
                    'status': False,
                    'message': f'Search failed with status {request.status_code}'
                }
        except Exception as error_search:
            return {
                'status': False,
                'message': str(error_search)
            }

    def get_series_details(self, series_slug):
        if not series_slug:
            return {'status': False, 'message': 'Series slug is required'}
        clean_slug = series_slug.rstrip("/").split("/")[-1] if "/" in series_slug else series_slug
        try:
            req = self.request.get(f"{self.BASE_WEB_URL}api/series/{clean_slug}", timeout=10)
            if req.status_code == 200:
                data = req.json()
                self.video_id = data.get("id")
                self.video_slug = data.get("slug", clean_slug)
                self.video_name = data.get("title")
                self.content_type = "tv_series"
                self.seasons_list = data.get("seasons", [])
                poster_path = data.get("posterPath", "")
                if poster_path and poster_path.startswith("/"):
                    self.poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                else:
                    self.poster = poster_path

                return {
                    'status': True,
                    'video_id': self.video_id,
                    'video_name': self.video_name,
                    'poster': self.poster,
                    'seasons': self.seasons_list,
                    'content_type': 'tv_series',
                    'data': data
                }
            else:
                return {'status': False, 'message': f'Failed to get series details for {clean_slug}'}
        except Exception as e:
            return {'status': False, 'message': f'Error getting series details: {str(e)}'}

    def get_season_episodes(self, series_slug, season_number):
        if not series_slug or season_number is None:
            return {'status': False, 'message': 'Series slug and season number required'}
        clean_slug = series_slug.rstrip("/").split("/")[-1] if "/" in series_slug else series_slug
        try:
            req = self.request.get(f"{self.BASE_WEB_URL}api/series/{clean_slug}/season/{season_number}", timeout=10)
            if req.status_code == 200:
                data = req.json()
                episodes = data.get("season", {}).get("episodes", [])
                return {
                    'status': True,
                    'episodes': episodes,
                    'season_info': data.get("season", {})
                }
            else:
                return {'status': False, 'message': f'Failed to get episodes for season {season_number}'}
        except Exception as e:
            return {'status': False, 'message': f'Error getting season episodes: {str(e)}'}

    def get_video_data(self, url):
        if not url:
            return {
                'status': False,
                'message': 'URL is required'
            }
        
        # Parse slug from URL or string
        clean_url = url.strip()
        if "/" in clean_url:
            slug = clean_url.rstrip("/").split("/")[-1]
        else:
            slug = clean_url

        self.seasons_list = []
        self.selected_episode = None

        try:
            # 1. Try movie endpoint
            request = self.request.get(
                url=f"{self.BASE_WEB_URL}api/movies/{slug}",
                timeout=10
            )
            if request.status_code == 200:
                data = request.json()
                self.video_id = data.get("id")
                self.video_slug = data.get("slug", slug)
                self.video_name = data.get("title")
                self.content_type = "movie"
                poster_path = data.get("posterPath", "")
                if poster_path and poster_path.startswith("/"):
                    self.poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                else:
                    self.poster = poster_path

                return {
                    'status': True,
                    'video_id': self.video_id,
                    'video_name': self.video_name,
                    'poster': self.poster,
                    'content_type': 'movie'
                }
            
            # 2. Try series endpoint if movie returned non-200 (e.g. 404)
            series_res = self.get_series_details(slug)
            if series_res.get("status"):
                return series_res

            return {
                'status': False,
                'message': f'Failed to get video/series data for {slug}'
            }
        except Exception as e:
            return {
                'status': False,
                'message': f'Error getting video data: {str(e)}'
            }

    def get_embed_url(self, video_id=None, item_type=None):
        target_id = video_id or self.video_id
        if not target_id:
            return {
                'status': False,
                'message': 'Video ID is required'
            }
        
        target_type = item_type or ("episode" if self.content_type == "episode" else "movie")
        play_path = "episode" if target_type == "episode" else "movie"

        try:
            # Step 1: get play-info
            play_info_url = f"{self.BASE_WEB_URL}api/watch/play-info/{play_path}/{target_id}"
            play_resp = self.request.get(play_info_url, timeout=10)
            if play_resp.status_code != 200:
                return {'status': False, 'message': f'Failed play-info request: {play_resp.status_code}'}
            
            play_data = play_resp.json()
            gate_token = play_data.get("gateToken")
            unlock_at = play_data.get("unlockAt", 0) / 1000.0
            server_now = play_data.get("serverNow", 0) / 1000.0

            wait_sec = max(0, unlock_at - server_now)
            if wait_sec > 0:
                logger.info(f"Unlocking stream gate... Waiting {wait_sec:.1f} seconds")
                import time
                time.sleep(wait_sec + 0.5)

            # Step 2: claimSession
            claim_url = f"{self.BASE_WEB_URL}api/watch/session/claim"
            claim_resp = self.request.post(
                claim_url,
                data=json.dumps({"gateToken": gate_token}),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if claim_resp.status_code != 200:
                return {'status': False, 'message': f'Failed claimSession: {claim_resp.status_code}'}

            claim_data = claim_resp.json()
            claim_token = claim_data.get("claim")
            redeem_url = claim_data.get("redeemUrl")

            if not claim_token or not redeem_url:
                return {'status': False, 'message': 'Invalid claim data returned'}

            # Step 3: redeem claim at redeemUrl
            redeem_sess = cffi_requests.Session(impersonate="chrome124")
            redeem_resp = redeem_sess.post(
                redeem_url,
                data=json.dumps({"claim": claim_token, "mode": "browser"}),
                headers={
                    "Content-Type": "application/json",
                    "Origin": self.get_origin(),
                    "Referer": self.get_referer()
                },
                timeout=10
            )
            if redeem_resp.status_code != 200:
                return {'status': False, 'message': f'Failed redeemUrl: {redeem_resp.status_code}'}

            redeem_data = redeem_resp.json()
            if redeem_data.get("code") != "ok" or not redeem_data.get("url"):
                return {'status': False, 'message': f'Redeem failed: {redeem_data.get("error", "Unknown")}'}

            self.embed_url = redeem_data.get("url")
            self.subtitles_list = redeem_data.get("subtitles", [])

            # Simpan cookies dari sesi redeem – dibutuhkan yt-dlp untuk autentikasi fragment CDN
            try:
                self.stream_cookies = dict(redeem_sess.cookies)
            except Exception:
                self.stream_cookies = {}

            # Tentukan Referer CDN yang benar dari embed_url (bukan BASE_WEB_URL)
            try:
                parsed_embed = urlparse(self.embed_url)
                self.stream_referer = f"{parsed_embed.scheme}://{parsed_embed.netloc}/"
            except Exception:
                self.stream_referer = self.BASE_WEB_URL

            return {
                'status': True,
                'embed_url': self.embed_url
            }
        except Exception as error_get_embed_url:
            return {
                'status': False,
                'message': str(error_get_embed_url)
            }

    def get_m3u8_url(self):
        if not self.embed_url:
            return {
                'status': False,
                'message': 'Embed URL is required'
            }

        try:
            sess = cffi_requests.Session(impersonate="chrome124")
            request = sess.get(
                self.embed_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                    "Referer": self.get_referer(),
                    "Origin": self.get_origin()
                },
                timeout=10
            )

            if request.status_code == 200:
                text = request.text
                self.master_m3u8_url = self.ensure_absolute_url(
                    getattr(request, "url", None) or self.embed_url,
                    base_url=self.embed_url,
                )
                tmp_variant_playlist = []
                id_cnt = 0

                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        res_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
                        res = res_match.group(1) if res_match else "Unknown"
                        bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                        bw = int(bw_match.group(1)) if bw_match else 0
                        
                        j = i + 1
                        while j < len(lines) and not lines[j].strip():
                            j += 1
                        if j < len(lines):
                            uri = lines[j].strip()
                            uri = self.ensure_absolute_url(
                                uri, base_url=self.master_m3u8_url
                            )
                            tmp_variant_playlist.append({
                                'bandwidth': bw,
                                'resolution': res,
                                'uri': uri,
                                'id': str(id_cnt)
                            })
                            id_cnt += 1

                is_variant_playlist = True if len(tmp_variant_playlist) > 1 else False
                self.variant_playlist = tmp_variant_playlist
                if tmp_variant_playlist:
                    self.m3u8_url = tmp_variant_playlist[0]["uri"]
                else:
                    self.m3u8_url = self.ensure_absolute_url(self.embed_url)

                return {
                    'status': True,
                    'm3u8_url': self.m3u8_url,
                    'variant_playlist': tmp_variant_playlist,
                    'is_variant_playlist': is_variant_playlist
                }
            else:
                return {
                    'status': False,
                    'message': f'Failed to get m3u8 playlist content: status {request.status_code}'
                }
        except Exception as error_get_m3u8_url:
            return {
                'status': False,
                'message': str(error_get_m3u8_url)
            }

    def ensure_absolute_url(self, url, base_url=None):
        """
        Ensures any relative stream path (like 'data-12345.json' or '/path/stream')
        is converted into a valid absolute HTTP/HTTPS URL and preserves authorization
        query tokens (like '?t=...') from base_url or embed_url.
        """
        if not url:
            return ""
        url = url.strip()

        target_base = base_url or self.embed_url or self.BASE_WEB_URL
        base_query = ""
        if target_base and "?" in target_base:
            base_query = urlparse(target_base).query

        if url.startswith("http://") or url.startswith("https://"):
            abs_url = url
        elif target_base and (target_base.startswith("http://") or target_base.startswith("https://")):
            abs_url = urljoin(target_base, url)
        elif url.startswith("/"):
            abs_url = "https://e2e.majorplay.net" + url
        else:
            abs_url = "https://e2e.majorplay.net/" + url.lstrip("/")

        # Preserve token query parameters (e.g. ?t=...) if missing in abs_url
        if base_query and "t=" in base_query and "t=" not in abs_url:
            delimiter = "&" if "?" in abs_url else "?"
            abs_url = f"{abs_url}{delimiter}{base_query}"

        return abs_url

    # ------------------------------------------------------------------
    # HLS MANIFEST PATCHER & FFMPEG DOWNLOADER
    # ------------------------------------------------------------------

    def _find_ffmpeg_binary(self):
        """
        Locate the ffmpeg binary: first checks PATH, then the local
        src/ffmpeg directory that may have been auto-extracted.
        Returns absolute path string or None.
        """
        ffmpeg = shutil.which('ffmpeg')
        if ffmpeg:
            return ffmpeg

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_dir = os.path.join(base_dir, 'src', 'ffmpeg')
        if os.path.exists(local_dir):
            for root, _dirs, files in os.walk(local_dir):
                for f in files:
                    if f.lower() == 'ffmpeg.exe':
                        candidate = os.path.join(root, f)
                        if os.path.exists(candidate):
                            return candidate
        return None

    def _fetch_and_patch_manifest(self, m3u8_url, temp_files=None, depth=0, sess=None):
        """
        Deep HLS Patcher dengan mekanisme Retry dan Connection Pooling.
        Mencegah timeout (curl 28) saat server CDN merespons lambat.
        """
        if temp_files is None:
            temp_files = []
            
        try:
            import time
            parsed = urlparse(m3u8_url)
            base_query = parsed.query

            if not self.stream_referer and self.embed_url:
                try:
                    parsed_embed = urlparse(self.embed_url)
                    self.stream_referer = f"{parsed_embed.scheme}://{parsed_embed.netloc}/"
                except Exception:
                    pass

            stream_referer = self.stream_referer or self.BASE_WEB_URL
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

            fetch_headers = {
                "User-Agent": user_agent,
                "Referer": stream_referer,
                "Origin": stream_referer.rstrip('/'),
                "Accept": "*/*"
            }
            if self.stream_cookies:
                cookie_str = '; '.join(f'{k}={v}' for k, v in self.stream_cookies.items())
                fetch_headers["Cookie"] = cookie_str

            # Gunakan session yang sama untuk mempercepat koneksi rekursif
            if sess is None:
                sess = cffi_requests.Session(impersonate="chrome124")

            # Sistem Retry: Coba hingga 3 kali jika terjadi Timeout
            resp = None
            last_err = None
            for attempt in range(3):
                try:
                    resp = sess.get(m3u8_url, headers=fetch_headers, timeout=30)
                    if resp.status_code == 200:
                        break
                except Exception as e:
                    last_err = e
                    logger.info(f"Timeout mengambil playlist (Attempt {attempt+1}/3). Mencoba lagi...")
                    time.sleep(2)
            
            if not resp or resp.status_code != 200:
                logger.warning(f"Gagal memuat manifest setelah 3 percobaan: {last_err or resp.status_code}")
                return None

            lines = resp.text.splitlines()
            patched = []
            is_master = any(line.startswith("#EXT-X-STREAM-INF") for line in lines)

            def _patch_uri_attr(tag_line):
                def _replace(m):
                    inner = m.group(1)
                    abs_uri = self.ensure_absolute_url(inner, base_url=m3u8_url)
                    if base_query and 't=' in base_query and 't=' not in abs_uri:
                        delimiter = '&' if '?' in abs_uri else '?'
                        abs_uri = f"{abs_uri}{delimiter}{base_query}"
                    
                    if is_master and depth == 0:
                        sub_file = self._fetch_and_patch_manifest(abs_uri, temp_files, depth=1, sess=sess)
                        if sub_file:
                            abs_uri = Path(sub_file).as_uri()
                    return f'URI="{abs_uri}"'
                return re.sub(r'URI="([^"]*)"', _replace, tag_line)

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    patched.append(line)
                    continue

                if stripped.startswith('#'):
                    if 'URI="' in stripped:
                        patched.append(_patch_uri_attr(line))
                    else:
                        patched.append(line)
                else:
                    abs_uri = self.ensure_absolute_url(stripped, base_url=m3u8_url)
                    if base_query and 't=' in base_query and 't=' not in abs_uri:
                        delimiter = '&' if '?' in abs_uri else '?'
                        abs_uri = f"{abs_uri}{delimiter}{base_query}"
                    
                    if is_master and depth == 0:
                        sub_file = self._fetch_and_patch_manifest(abs_uri, temp_files, depth=1, sess=sess)
                        if sub_file:
                            patched.append(Path(sub_file).as_uri())
                        else:
                            patched.append(abs_uri)
                    else:
                        patched.append(abs_uri)

            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.m3u8', delete=False, encoding='utf-8')
            tmp.write('\n'.join(patched))
            tmp.close()
            temp_files.append(tmp.name)
            logger.info(f"Patched HLS manifest (Depth {depth}): {tmp.name}")
            return tmp.name

        except Exception as exc:
            logger.warning(f"Manifest patch error: {exc}")
            return None

            lines = resp.text.splitlines()
            patched = []

            def _patch_uri_attr(tag_line):
                """
                Rewrite URI="..." attribute(s) inside HLS tag lines
                (e.g. #EXT-X-MAP, #EXT-X-KEY, #EXT-X-MEDIA) to absolute
                URLs with the auth token appended.
                """
                def _replace(m):
                    inner = m.group(1)
                    abs_uri = self.ensure_absolute_url(inner, base_url=m3u8_url)
                    if base_query and 't=' in base_query and 't=' not in abs_uri:
                        delimiter = '&' if '?' in abs_uri else '?'
                        abs_uri = f"{abs_uri}{delimiter}{base_query}"
                    return f'URI="{abs_uri}"'
                return re.sub(r'URI="([^"]*)"', _replace, tag_line)

            for line in lines:
                stripped = line.strip()
                # Plain segment URI lines: non-empty, don't start with '#'
                if stripped and not stripped.startswith('#'):
                    abs_uri = self.ensure_absolute_url(stripped, base_url=m3u8_url)
                    # Append auth token if not already present
                    if base_query and 't=' in base_query and 't=' not in abs_uri:
                        delimiter = '&' if '?' in abs_uri else '?'
                        abs_uri = f"{abs_uri}{delimiter}{base_query}"
                    patched.append(abs_uri)
                elif stripped.startswith('#') and 'URI="' in stripped:
                    # HLS tag lines that carry a URI attribute (#EXT-X-MAP, #EXT-X-KEY, etc.)
                    patched.append(_patch_uri_attr(line))
                else:
                    patched.append(line)

            # Write patched manifest to a temp file
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.m3u8', delete=False, encoding='utf-8'
            )
            tmp.write('\n'.join(patched))
            tmp.close()
            logger.info(f"Patched HLS manifest written to temp file: {tmp.name}")
            return tmp.name

        except Exception as exc:
            logger.warning(f"_fetch_and_patch_manifest failed: {exc}")
            return None

    def _run_download_process(self, cmd, output_path, progress_callback):
        """
        Shared helper: run *cmd* as a subprocess, stream its stdout to the
        logger and *progress_callback*, and handle cancel / pause signals.
        Returns a result dict with ``status``, ``message``, and optionally
        ``path``.
        """
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            self.download_process = process

            for line in iter(process.stdout.readline, ''):
                if self.download_cancelled or self.download_paused:
                    break
                line_clean = line.strip()
                if line_clean:
                    logger.info(line_clean)
                    if progress_callback:
                        try:
                            progress_callback(line_clean)
                        except Exception:
                            pass

            process.stdout.close()
            return_code = process.wait()
            self.download_process = None

            if self.download_cancelled:
                self.cleanup_partial_files(output_path)
                logger.info("Download cancelled and temporary files cleaned up.")
                return {'status': False, 'message': 'Download cancelled'}

            if self.download_paused:
                logger.info("Download paused.")
                return {'status': False, 'message': 'Download paused'}

            if return_code == 0:
                logger.success(f"Download completed: {output_path}")
                return {'status': True, 'message': 'Download success', 'path': output_path}

            logger.error(f"Downloader process failed with exit code: {return_code}")
            return {'status': False, 'message': f'Process returned code {return_code}'}

        except Exception as exc:
            self.download_process = None
            logger.error(f"Download process exception: {exc}")
            return {'status': False, 'message': str(exc)}

    def download_with_ytdlp(self, stream_url=None, output_filename=None, progress_callback=None):
        """
        Download an HLS/M3U8 stream with yt-dlp, retaining separate audio
        renditions from the master playlist when available.

        Strategy:
        1. Pre-fetch the HLS manifest and rewrite every segment URI to an
           absolute URL containing the CDN auth token (``?t=…``).  This
           prevents HTTP 401 errors caused by yt-dlp/ffmpeg dropping the
           ``?t=`` query-string when resolving relative segment URIs.
        2. Download via **yt-dlp** (rather than invoking ffmpeg directly) so that
           segment URLs with non-standard extensions (e.g. ``.js``,
           ``.webp``) are handled transparently.  ffmpeg rejects these with
           "detected format … mismatches allowed extensions in url".
        3. Use the master playlist for downloads so yt-dlp can discover and
           mux any separate audio rendition, while honoring the selected height.
           Fall back to the original URL if manifest patching failed.
        """
        raw_url = stream_url or self.download_stream_url or self.m3u8_url or self.embed_url
        if not raw_url:
            return {'status': False, 'message': 'No stream URL available to download'}

        selected_variant = next(
            (
                variant for variant in (self.variant_playlist or [])
                if variant.get('uri') == self.m3u8_url
            ),
            None,
        )
        if (
            selected_variant
            and self.master_m3u8_url
            and raw_url in (self.m3u8_url, self.master_m3u8_url)
        ):
            raw_url = self.master_m3u8_url
        else:
            selected_variant = None

        self.download_stream_url = raw_url
        self.download_cancelled = False
        self.download_paused = False

        url_to_download = self.ensure_absolute_url(raw_url, base_url=self.embed_url)
        if not (url_to_download.startswith('http://') or url_to_download.startswith('https://')):
            logger.error(f"Invalid stream URL: '{url_to_download}'")
            return {
                'status': False,
                'message': f"Invalid stream URL: '{url_to_download}' (must be absolute HTTP/HTTPS URL)",
            }

        # ── Output path ───────────────────────────────────────────────
        # ---> Mulai dari deklarasi variabel download_dir dan user_agent:
        # ── Output path ───────────────────────────────────────────────
        download_dir = 'Unduhan Film/Series'
        os.makedirs(download_dir, exist_ok=True)

        safe_title = (
            ''.join(c for c in (self.video_name or 'video') if c.isalnum() or c in (' ', '_', '-'))
            .rstrip()
            .replace(' ', '_')
        )
        if not output_filename:
            output_filename = f"{safe_title}.mp4"
        elif not output_filename.endswith('.mp4'):
            output_filename = f"{output_filename}.mp4"

        base_name = os.path.basename(output_filename)
        output_path = os.path.abspath(os.path.join(download_dir, base_name))
        self.download_output_path = output_path

        user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        )

        if not self.stream_referer and self.embed_url:
            try:
                self.stream_referer = f"{urlparse(self.embed_url).scheme}://{urlparse(self.embed_url).netloc}/"
            except Exception:
                pass

        stream_referer = self.stream_referer or self.BASE_WEB_URL
        stream_origin  = stream_referer.rstrip('/')

        # ── Patch manifest (Mendukung Deep Patching) ────────────────
        temp_manifests = []
        patched_manifest_path = self._fetch_and_patch_manifest(url_to_download, temp_manifests)

        if patched_manifest_path:
            target_input = Path(patched_manifest_path).as_uri()
        else:
            target_input = url_to_download

        logger.info(f"Starting yt-dlp download for: {self.video_name or safe_title}")

        cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--enable-file-urls',
            '--format', 'bestvideo+bestaudio/best',
            '--merge-output-format', 'mp4',
            '--referer', stream_referer,
            '--user-agent', user_agent,
            '--add-header', f'Referer: {stream_referer}',
            '--add-header', f'User-Agent: {user_agent}',
            '--add-header', f'Origin: {stream_origin}',
            '--add-header', 'Accept: */*',
            '--no-check-certificates',
            
            # GANTI MENJADI 1 AGAR TIDAK DIBLOKIR ANTI-LEECH
            '--concurrent-fragments', '1', 
            
            '--retries', '10',
            '--fragment-retries', '10',
            '--hls-use-mpegts',
            '--newline',
        ]

        ffmpeg_path = self._find_ffmpeg_binary()
        if ffmpeg_path:
            cmd.extend(['--ffmpeg-location', os.path.dirname(ffmpeg_path)])

        cmd.extend(['-o', output_path, target_input])

        if self.stream_cookies:
            cookie_str = '; '.join(f'{k}={v}' for k, v in self.stream_cookies.items())
            cmd.extend(['--add-header', f'Cookie: {cookie_str}'])

        try:
            return self._run_download_process(cmd, output_path, progress_callback)
        finally:
            # Pastikan semua temporary file (Master & Variants) terhapus bersih
            for tmp_file in temp_manifests:
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except Exception:
                    pass

    def download_m3u8(self, progress_callback=None):
        return self.download_with_ytdlp(progress_callback=progress_callback)

    def get_available_subtitles(self):
        """
        Return the list of available subtitles with lang code and label.
        Each entry: {'lang': 'id', 'label': 'Indonesian', 'path': 'https://...'}
        """
        if not self.subtitles_list:
            return []

        LANG_NAMES = {
            'id': 'Indonesian', 'en': 'English', 'es': 'Spanish',
            'fr': 'French', 'de': 'German', 'pt': 'Portuguese',
            'it': 'Italian', 'nl': 'Dutch', 'ja': 'Japanese',
            'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic',
            'hi': 'Hindi', 'th': 'Thai', 'vi': 'Vietnamese',
            'ms': 'Malay', 'tr': 'Turkish', 'ru': 'Russian',
            'pl': 'Polish', 'sv': 'Swedish', 'da': 'Danish',
            'no': 'Norwegian', 'fi': 'Finnish', 'el': 'Greek',
            'cs': 'Czech', 'ro': 'Romanian', 'hu': 'Hungarian',
            'uk': 'Ukrainian', 'hr': 'Croatian', 'bg': 'Bulgarian',
        }
        result = []
        for sub in self.subtitles_list:
            lang = sub.get('lang', 'unknown')
            label = sub.get('label') or LANG_NAMES.get(lang, lang.upper())
            result.append({
                'lang': lang,
                'label': label,
                'path': sub.get('path', ''),
            })
        return result

    def download_subtitles_for_video(self, selected_langs=None, output_dir=None):
        """
        Download subtitle files for the current video.

        Args:
            selected_langs: List of language codes to download (e.g. ['id', 'en']).
                            If None or empty, downloads all available subtitles.
            output_dir: Directory to save subtitle files. Defaults to 'Unduhan Film/Series'.

        Returns:
            dict with 'status', 'downloaded' (list of saved paths), 'message'.
        """
        try:
            if not self.subtitles_list:
                return {
                    'status': False,
                    'message': 'Tidak ada subtitle yang tersedia untuk video ini',
                    'downloaded': []
                }

            download_dir = output_dir or 'Unduhan Film/Series'
            os.makedirs(download_dir, exist_ok=True)

            safe_name = (
                ''.join(c for c in (self.video_name or 'video') if c.isalnum() or c in (' ', '_', '-'))
                .rstrip()
                .replace(' ', '_')
            )

            downloaded_files = []
            errors = []

            for sub in self.subtitles_list:
                lang = sub.get('lang', 'unknown')

                # Filter by selected languages if specified
                if selected_langs and lang not in selected_langs:
                    continue

                sub_url = sub.get('path', '')
                if not sub_url:
                    errors.append(f"Subtitle URL kosong untuk bahasa: {lang}")
                    continue

                try:
                    logger.info(f"Downloading subtitle [{lang}]: {sub_url}")
                    subtitle_request = requests.get(url=sub_url, timeout=15)

                    if subtitle_request.status_code != 200:
                        errors.append(f"Gagal download subtitle [{lang}]: HTTP {subtitle_request.status_code}")
                        continue

                    # Save VTT file with language code
                    vtt_filename = os.path.join(download_dir, f"{safe_name}.{lang}.vtt")
                    with open(vtt_filename, 'wb') as f:
                        f.write(subtitle_request.content)

                    # Convert VTT to SRT
                    self.convert_vtt_to_srt(vtt_filename)
                    srt_filename = os.path.join(download_dir, f"{safe_name}.{lang}.srt")

                    if os.path.exists(srt_filename):
                        downloaded_files.append(srt_filename)
                        logger.success(f"Subtitle [{lang}] saved: {os.path.basename(srt_filename)}")
                    else:
                        # SRT conversion might save without lang code; try old pattern
                        alt_srt = os.path.join(download_dir, f"{safe_name}.srt")
                        if os.path.exists(alt_srt):
                            # Rename to include language code
                            os.rename(alt_srt, srt_filename)
                            downloaded_files.append(srt_filename)
                            logger.success(f"Subtitle [{lang}] saved: {os.path.basename(srt_filename)}")
                        else:
                            # Keep VTT as fallback
                            downloaded_files.append(vtt_filename)
                            logger.warning(f"Subtitle [{lang}] saved as VTT (SRT conversion skipped): {os.path.basename(vtt_filename)}")

                except Exception as sub_err:
                    errors.append(f"Error downloading subtitle [{lang}]: {str(sub_err)}")
                    logger.warning(f"Error downloading subtitle [{lang}]: {sub_err}")

            if downloaded_files:
                self.is_subtitle = True
                msg = f"Berhasil download {len(downloaded_files)} subtitle"
                if errors:
                    msg += f" ({len(errors)} gagal)"
                return {
                    'status': True,
                    'message': msg,
                    'downloaded': downloaded_files,
                }
            else:
                return {
                    'status': False,
                    'message': 'Gagal download semua subtitle' + (f': {"; ".join(errors)}' if errors else ''),
                    'downloaded': [],
                }

        except Exception as e:
            logger.error(f"Error in download_subtitles_for_video: {e}")
            return {
                'status': False,
                'message': str(e),
                'downloaded': [],
            }

    def get_subtitle(self, download=True):
        try:
            if not self.subtitles_list:
                self.is_subtitle = False
                return {
                    'status': False,
                    'message': 'Subtitle not found'
                }

            # Prioritize Indonesian ('id') or English ('en') subtitle
            selected_sub = None
            for sub in self.subtitles_list:
                if sub.get('lang') == 'id':
                    selected_sub = sub
                    break
                elif sub.get('lang') == 'en' and not selected_sub:
                    selected_sub = sub
            if not selected_sub:
                selected_sub = self.subtitles_list[0]

            sub_url = selected_sub.get('path')
            if not sub_url:
                self.is_subtitle = False
                return {'status': False, 'message': 'Subtitle URL empty'}

            if download:
                download_dir = "Unduhan Film/Series"
                os.makedirs(download_dir, exist_ok=True)
                subtitle_request = requests.get(url=sub_url)
                safe_name = "".join([c for c in (self.video_name or "subtitle") if c.isalnum() or c in (' ', '_', '-')]).rstrip().replace(" ", "_")
                vtt_filename = os.path.join(download_dir, safe_name + '.vtt')
                with open(vtt_filename, 'wb') as subtitle_file:
                    subtitle_file.write(subtitle_request.content)
                self.convert_vtt_to_srt(vtt_filename)
                self.is_subtitle = True
                srt_path = os.path.join(download_dir, safe_name + '.srt')
                return {
                    'status': True,
                    'subtitle': srt_path,
                }

            self.is_subtitle = True
            return {
                'status': True,
                'subtitle': sub_url
            }
        except Exception as error_get_subtitle:
            return {
                'status': False,
                'message': str(error_get_subtitle)
            }

    @staticmethod
    def find_executable_player():
        """
        Validates and locates available external video player executable (ffplay or VLC).
        Returns tuple: (player_type, player_path) or (None, None).
        """
        # 1. Check ffplay in PATH
        ffplay_path = shutil.which("ffplay")
        if ffplay_path and os.path.exists(ffplay_path):
            return ("ffplay", ffplay_path)

        # 2. Check local extracted ffmpeg bin directory (Windows auto-download)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_ffmpeg_dir = os.path.join(base_dir, "src", "ffmpeg")
        if os.path.exists(local_ffmpeg_dir):
            for root, dirs, files in os.walk(local_ffmpeg_dir):
                for file in files:
                    if file.lower() == "ffplay.exe":
                        target_path = os.path.join(root, file)
                        if os.path.exists(target_path):
                            return ("ffplay", target_path)

        # 3. Check VLC in PATH
        vlc_path = shutil.which("vlc")
        if vlc_path and os.path.exists(vlc_path):
            return ("vlc", vlc_path)

        # 4. Check standard VLC installation paths on Windows
        vlc_standard_paths = [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
        ]
        for v_path in vlc_standard_paths:
            if os.path.exists(v_path):
                return ("vlc", v_path)

        return (None, None)

    def play_stream_instantly(self, stream_url=None, video_name=None, subtitle=None):
        """
        Stream video directly via ffplay or VLC with HTTP referer & user-agent headers.
        Does not download or save physical mp4 files to disk.
        Returns dict with status, message, and player subprocess handle.
        """
        raw_url = stream_url or self.m3u8_url or self.embed_url
        if not raw_url:
            err_msg = "No stream URL available for playback"
            logger.error(err_msg)
            return {'status': False, 'message': err_msg}

        url_to_play = self.ensure_absolute_url(raw_url, base_url=self.embed_url)
        if not (url_to_play.startswith("http://") or url_to_play.startswith("https://")):
            err_msg = f"Invalid stream URL: '{url_to_play}'"
            logger.error(err_msg)
            return {'status': False, 'message': err_msg}

        # 1. Validate player existence
        player_type, player_path = self.find_executable_player()
        if not player_type or not player_path:
            err_msg = "Player executable (ffplay/VLC) not found in system PATH."
            logger.error(err_msg)
            return {'status': False, 'message': err_msg}

        title = video_name or self.video_name or "IDLIX Player"
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        referer = self.BASE_WEB_URL

        logger.info(f"Starting instant stream playback for: {title} via {player_type.upper()} ({player_path})")

        try:
            if player_type == "ffplay":
                cmd_ytdlp = [
                    sys.executable, "-m", "yt_dlp",
                    "--referer", referer,
                    "--user-agent", user_agent,
                    "--add-header", f"Referer: {referer}",
                    "--add-header", f"User-Agent: {user_agent}",
                    "--add-header", f"Origin: {referer.rstrip('/')}",
                    "--no-check-certificates",
                    "-o", "-",
                    url_to_play
                ]
                cmd_player = [
                    player_path,
                    "-i", "-",
                    "-window_title", f"IDLIX Player - {title}",
                    "-autoexit"
                ]
                if subtitle and os.path.exists(subtitle):
                    sub_clean = os.path.abspath(subtitle).replace("\\", "/").replace(":", "\\:")
                    cmd_player.extend(["-vf", f"subtitles='{sub_clean}'"])

                p_ytdlp = subprocess.Popen(cmd_ytdlp, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                p_player = subprocess.Popen(cmd_player, stdin=p_ytdlp.stdout)
                p_ytdlp.stdout.close()

                logger.success(f"Stream player (ffplay via yt-dlp pipe) launched successfully (PIDs: player={p_player.pid}, ytdlp={p_ytdlp.pid})")

                return {
                    'status': True,
                    'message': 'Playing via yt-dlp pipe to ffplay',
                    'player_process': p_player,
                    'ytdlp_process': p_ytdlp
                }

            elif player_type == "vlc":
                cmd_player = [
                    player_path,
                    url_to_play,
                    f"--http-referrer={referer}",
                    f"--http-user-agent={user_agent}",
                    f"--meta-title=IDLIX Player - {title}",
                    "--play-and-exit"
                ]
                if subtitle and os.path.exists(subtitle):
                    cmd_player.append(f"--sub-file={os.path.abspath(subtitle)}")

                p_player = subprocess.Popen(cmd_player)
                logger.success(f"Stream player (VLC) launched successfully (PID: {p_player.pid})")

                return {
                    'status': True,
                    'message': 'Playing via VLC',
                    'player_process': p_player,
                    'ytdlp_process': None
                }
            else:
                err_msg = "Unsupported player type"
                logger.error(err_msg)
                return {'status': False, 'message': err_msg}

        except (FileNotFoundError, OSError, subprocess.SubprocessError) as error_launch:
            err_msg = f"Failed to launch player ({player_type}): {error_launch}"
            logger.error(err_msg)
            return {
                'status': False,
                'message': err_msg
            }
        except Exception as error_play:
            err_msg = f"Unexpected error starting stream player: {error_play}"
            logger.error(err_msg)
            return {
                'status': False,
                'message': err_msg
            }

    def play_m3u8(self):
        try:
            if not self.m3u8_url:
                return {
                    'status': False,
                    'message': 'M3U8 URL is required'
                }

            safe_name = "".join([c for c in (self.video_name or "") if c.isalnum() or c in (' ', '_', '-')]).rstrip().replace(" ", "_")
            sub_file = safe_name + '.srt' if (self.is_subtitle and os.path.exists(safe_name + '.srt')) else None

            res = self.play_stream_instantly(subtitle=sub_file)
            if res.get('status') and res.get('player_process'):
                res['player_process'].wait()
            return res
        except Exception as error_play_m3u8:
            return {
                'status': False,
                'message': str(error_play_m3u8)
            }

    @staticmethod
    def convert_vtt_to_srt(vtt_file):
        convert_file = ConvertFile(vtt_file, "utf-8")
        convert_file.convert()

    def set_m3u8_url(self, m3u8_url):
        self.m3u8_url = self.ensure_absolute_url(m3u8_url, base_url=self.embed_url)
