import logging,shutil
import re
import threading
import sys
import argparse
import subprocess
import torch
from flask import Flask, request, render_template, jsonify, send_from_directory, Response
from flask_cors import CORS
import os
from gevent.pywsgi import WSGIServer, WSGIHandler, LoggingLogAdapter
from logging.handlers import RotatingFileHandler
import warnings
warnings.filterwarnings('ignore')
import stslib
from stslib import cfg, tool
from stslib.cfg import ROOT_DIR
from faster_whisper import WhisperModel
import time
from werkzeug.utils import secure_filename
import uuid
import json
import pymysql
from pymysql.cursors import DictCursor
from dotenv import dotenv_values

class CustomRequestHandler(WSGIHandler):
    def log_request(self):
        pass


# 配置日志
# 禁用 Werkzeug 默认的日志处理器
log = logging.getLogger('werkzeug')
log.handlers[:] = []
log.setLevel(logging.WARNING)
app = Flask(__name__, static_folder=os.path.join(ROOT_DIR, 'static'), static_url_path='/static',  template_folder=os.path.join(ROOT_DIR, 'templates'))
CORS(app)
root_log = logging.getLogger()  # Flask的根日志记录器
root_log.handlers = []
root_log.setLevel(logging.WARNING)

# 配置日志
app.logger.setLevel(logging.WARNING)  # 设置日志级别为 INFO
# 创建 RotatingFileHandler 对象，设置写入的文件路径和大小限制
file_handler = RotatingFileHandler(os.path.join(ROOT_DIR, 'sts.log'), maxBytes=1024 * 1024, backupCount=5)
# 创建日志的格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# 设置文件处理器的级别和格式
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)
# 将文件处理器添加到日志记录器中
app.logger.addHandler(file_handler)


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(app.config['STATIC_FOLDER'], filename)


@app.route('/')
def index():
    sets=cfg.parse_ini()
    return render_template("index.html",
       devtype=sets.get('devtype'),
       lang_code=cfg.lang_code,
       language=cfg.LANG,
       version=stslib.version_str,
       root_dir=ROOT_DIR.replace('\\', '/'),
       model_list=cfg.sets.get('model_list')
    )


# 上传音频
@app.route('/upload', methods=['POST'])
def upload():
    try:
        # 获取上传的文件
        audio_file = request.files['audio']
        # 如果是mp4
        noextname, ext = os.path.splitext(audio_file.filename)
        ext = ext.lower()
        # 如果是视频，先分离
        wav_file = os.path.join(cfg.TMP_DIR, f'{noextname}.wav')
        if os.path.exists(wav_file) and os.path.getsize(wav_file) > 0:
            return jsonify({'code': 0, 'msg': cfg.transobj['lang1'], "data": os.path.basename(wav_file)})
        
        msg = ""
        video_file = os.path.join(cfg.TMP_DIR, f'{noextname}{ext}')
        audio_file.save(video_file)
        params = [
            "-i",
            video_file,
            "-ar",
            "16000",
            "-ac",
            "1",
            wav_file
        ]  
        try:
            rs = tool.runffmpeg(params)
        except Exception as e:
            return jsonify({"code": 1, "msg": str(e)})
        if rs != 'ok':
            return jsonify({"code": 1, "msg": rs})
        msg = "," + cfg.transobj['lang9']

        # 返回成功的响应
        return jsonify({'code': 0, 'msg': cfg.transobj['lang1'] + msg, "data": os.path.basename(wav_file)})
    except Exception as e:
        app.logger.error(f'[upload]error: {e}')
        return jsonify({'code': 2, 'msg': cfg.transobj['lang2']})

# 后端线程处理
def shibie():
    while 1:
        if len(cfg.TASK_QUEUE)<1:
            # 不存在任务，卸载所有模型
            for model_key in cfg.MODEL_DICT:
                try:
                    cfg.MODEL_DICT[model_key]=None
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except:
                    pass
            time.sleep(2)
            continue
    

        sets=cfg.parse_ini()
        task=cfg.TASK_QUEUE.pop(0)
        print(f'{task=}')
        wav_name = task['wav_name']
        model = task['model']
        language = task['language']
        data_type = task['data_type']
        wav_file = task['wav_file']
        key = task['key']
        prompt=task.get('prompt',sets.get('initial_prompt_zh'))
        
        cfg.progressbar[key]=0
        print(f'{model=}')
        modelobj=cfg.MODEL_DICT.get(model)
        if not modelobj:
            try:
                print(f'开始加载模型，若不存在将自动下载')
                modelobj= WhisperModel(
                    model  if not model.startswith('distil') else  model.replace('-whisper', ''), 
                    device=sets.get('devtype'), 
                    download_root=cfg.ROOT_DIR + "/models"
                )
                cfg.MODEL_DICT[model]=modelobj
            except Exception as e:
                err=f'从 huggingface.co 下载模型 {model} 失败，请检查网络连接' if model.find('/')>0 else ''
                cfg.progressresult[key]='error:'+err+str(e)
                return
        try:
            segments,info = modelobj.transcribe(
                wav_file,  
                beam_size=sets.get('beam_size'),
                best_of=sets.get('best_of'),
                condition_on_previous_text=sets.get('condition_on_previous_text'),
                vad_filter=sets.get('vad'),  
                language=language if language and language !='auto' else None, 
                initial_prompt=prompt
            )
            total_duration = round(info.duration, 2)  # Same precision as the Whisper timestamps.

            raw_subtitles = []
            for segment in segments:
                cfg.progressbar[key]=round(segment.end/total_duration, 2)
                start = int(segment.start * 1000)
                end = int(segment.end * 1000)
                startTime = tool.ms_to_time_string(ms=start)
                endTime = tool.ms_to_time_string(ms=end)
                text = segment.text.strip().replace('&#39;', "'")
                text = re.sub(r'&#\d+;', '', text)

                # 无有效字符
                if not text or re.match(r'^[，。、？‘’“”；：（｛｝【】）:;"\'\s \d`!@#$%^&*()_+=.,?/\\-]*$', text) or len(
                        text) <= 1:
                    continue
                if cfg.cc is not None:
                    text=cfg.cc.convert(text)
                if data_type == 'json':
                    # 原语言字幕
                    raw_subtitles.append(
                        {"line": len(raw_subtitles) + 1, "start_time": startTime, "end_time": endTime, "text": text})
                elif data_type == 'text':
                    raw_subtitles.append(text)
                else:
                    raw_subtitles.append(f'{len(raw_subtitles) + 1}\n{startTime} --> {endTime}\n{text}\n')
            cfg.progressbar[key]=1
            if data_type != 'json':
                raw_subtitles = "\n".join(raw_subtitles)
            cfg.progressresult[key]=raw_subtitles
        except Exception as e:
            cfg.progressresult[key]='error:'+str(e)
            print(str(e))



# params
# wav_name:tmp下的wav文件
# model 模型名称
@app.route('/process', methods=['GET', 'POST'])
def process():
    # 原始字符串
    wav_name = request.form.get("wav_name","").strip()
    if not wav_name:
        return jsonify({"code": 1, "msg": f"No file had uploaded"})
    model = request.form.get("model")
    # 语言
    language = request.form.get("language")
    # 返回格式 json txt srt
    data_type = request.form.get("data_type")
    wav_file = os.path.join(cfg.TMP_DIR, wav_name)
    if not os.path.exists(wav_file):
        return jsonify({"code": 1, "msg": f"{wav_file} {cfg.transobj['lang5']}"})

    key=f'{wav_name}{model}{language}{data_type}'
    #重设结果为none
    cfg.progressresult[key]=None
    # 重设进度为0
    cfg.progressbar[key]=0
    #存入任务队列
    cfg.TASK_QUEUE.append({"wav_name":wav_name, "model":model, "language":language, "data_type":data_type, "wav_file":wav_file, "key":key})
    return jsonify({"code":0, "msg":"ing"})

# 前端获取进度及完成后的结果
@app.route('/progressbar', methods=['GET', 'POST'])
def progressbar():
    # 原始字符串
    wav_name = request.form.get("wav_name").strip()
    model_name = request.form.get("model")
    # 语言
    language = request.form.get("language")
    # 返回格式 json txt srt
    data_type = request.form.get("data_type")
    key = f'{wav_name}{model_name}{language}{data_type}'
    if key in cfg.progressresult and  isinstance(cfg.progressresult[key],str) and cfg.progressresult[key].startswith('error:'):
        return jsonify({"code":1,"msg":cfg.progressresult[key][6:]})

    progressbar = cfg.progressbar.get(key)
    if progressbar is None:
        return jsonify({"code":1,"msg":"No this file"}),500
    if progressbar>=1:
        return jsonify({"code":0, "data":progressbar, "msg":"ok", "result":cfg.progressresult[key]})
    return jsonify({"code":0, "data":progressbar, "msg":"ok"})


"""
# openai兼容格式
from openai import OpenAI

client = OpenAI(api_key='123',base_url='http://127.0.0.1:9977/v1')
audio_file= open("C:/users/c1/videos/60.wav", "rb")

transcription = client.audio.transcriptions.create(
    model="tiny", 
    file=audio_file,
    response_format="text" # srt json
)

print(transcription.text)

"""
@app.route('/v1/audio/transcriptions', methods=['POST'])
def transcribe_audio():
    if 'file' not in request.files:
        return jsonify({"error": "请求中未找到文件部分"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "未选择文件"}), 400
    if not shutil.which('ffmpeg'):
        return jsonify({"error": "FFmpeg 未安装或未在系统 PATH 中"}), 500
    if not shutil.which('ffprobe'):
        return jsonify({"error": "ffprobe 未安装或未在系统 PATH 中"}), 500
    # 用 model 参数传递特殊要求，例如 ----*---- 分隔字符串和json
    model = request.form.get('model', '')
    # prompt 用于获取语言
    prompt = request.form.get('prompt', '')
    language = request.form.get('language', '')
    response_format = request.form.get('response_format', 'text')

    original_filename = secure_filename(file.filename)
    wav_name = str(uuid.uuid4())+f"_{original_filename}"
    temp_original_path = os.path.join(cfg.TMP_DIR,  wav_name)
    wav_file = os.path.join(cfg.TMP_DIR,  wav_name+"-target.wav")
    file.save(temp_original_path)
    
    params = [
            "-i",
            temp_original_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            wav_file
        ]
        
    try:
        print(params)
        rs = tool.runffmpeg(params)
        if rs != 'ok':
            return jsonify({"error": rs}),500
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}),500

    try:
        res=_api_process(model_name=model,wav_file=wav_file,language=language,response_format=response_format,prompt=prompt)
        if response_format=='srt':
            return Response(res,mimetype='text/plain')
        
        if response_format =='text':
            res={"text":res}            
        return jsonify(res)
    except Exception as e:
        return jsonify({"error":str(e)}),500

# 原api接口，保留兼容
@app.route('/api',methods=['GET','POST'])
def api():
    try:
        # 获取上传的文件
        audio_file = request.files['file']
        model_name = request.form.get("model")
        language = request.form.get("language")
        response_format = request.form.get("response_format",'srt')

        basename = os.path.basename(audio_file.filename)
        video_file = os.path.join(cfg.TMP_DIR, basename)        
        audio_file.save(video_file)
        
        wav_file = os.path.join(cfg.TMP_DIR, f'{basename}-{time.time()}.wav')
        params = [
            "-i",
            video_file,
            "-ar",
            "16000",
            "-ac",
            "1",
            wav_file
        ]
        
        try:
            print(params)
            rs = tool.runffmpeg(params)
            if rs != 'ok':
                return jsonify({"code": 1, "msg": rs})
        except Exception as e:
            print(e)
            return jsonify({"code": 1, "msg": str(e)})
        
        raw_subtitles=_api_process(model_name=model_name,wav_file=wav_file,language=language,response_format=response_format)
        # _api_process already returns the correct format (string for text/srt, list for json)
        # No need to join again - it's already processed
        return jsonify({"code": 0, "msg": 'ok', "data": raw_subtitles})
    except Exception as e:
        print(e)
        app.logger.error(f'[api]error: {e}')
        return jsonify({'code': 2, 'msg': str(e)})

# api接口调用
def _api_process(model_name,wav_file,language=None,response_format="text",prompt=None):
    try:
        sets=cfg.parse_ini()
        if model_name.startswith('distil-'):
            model_name = model_name.replace('-whisper', '')
        model = WhisperModel(
            model_name, 
            device=sets.get('devtype'), 
            download_root=cfg.ROOT_DIR + "/models"
        )
    except Exception as e:
        raise
        
    segments,info = model.transcribe(
        wav_file, 
        beam_size=sets.get('beam_size'),
        best_of=sets.get('best_of'),
        temperature=0 if sets.get('temperature')==0 else [0.0,0.2,0.4,0.6,0.8,1.0],
        condition_on_previous_text=sets.get('condition_on_previous_text'),
        vad_filter=sets.get('vad'),    
        language=language if language and language !='auto' else None,
        initial_prompt=sets.get('initial_prompt_zh') if not prompt else prompt
    )
    raw_subtitles = []
    for  segment in segments:
        start = int(segment.start * 1000)
        end = int(segment.end * 1000)
        startTime = tool.ms_to_time_string(ms=start)
        endTime = tool.ms_to_time_string(ms=end)
        text = segment.text.strip().replace('&#39;', "'")
        text = re.sub(r'&#\d+;', '', text)

        # 无有效字符
        if not text or re.match(r'^[，。、？''""；：（｛｝【】）:;"\'\s \d`!@#$%^&*()_+=.,?/\\-]*$', text) or len(text) <= 1:
            continue
        if response_format == 'json':
            # 原语言字幕
            raw_subtitles.append(
                {"line": len(raw_subtitles) + 1, "start_time": startTime, "end_time": endTime, "text": text})
        elif response_format == 'text':
            raw_subtitles.append(text)
        else:
            raw_subtitles.append(f'{len(raw_subtitles) + 1}\n{startTime} --> {endTime}\n{text}\n')
    
    # Handle empty results - ensure raw_subtitles is always defined
    if response_format != 'json':
        # Convert list to string, or return empty string if no valid segments
        raw_subtitles = "\n".join(raw_subtitles) if raw_subtitles else ""
    # For json format, return empty list if no valid segments
    return raw_subtitles


def _cookies_header_from_db(cookies_value):
    """将 crawler_cookies_account.cookies 转为 Cookie 请求头字符串。支持 JSON 或 key=val; 格式。"""
    if not cookies_value:
        return None
    s = (cookies_value or "").strip()
    if not s:
        return None
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            return "; ".join(f"{k}={v}" for k, v in d.items() if v)
    except (json.JSONDecodeError, TypeError):
        pass
    return s if "=" in s else None


def _merge_dotenv_files(*rel_paths):
    """按顺序合并多个 .env 文件，后者覆盖前者（值非空才写入）。"""
    merged = {}
    for rel in rel_paths:
        path = os.path.join(ROOT_DIR, rel)
        if not os.path.isfile(path):
            continue
        for k, v in dotenv_values(path).items():
            if v is not None and str(v).strip() != "":
                merged[k] = str(v).strip()
    return merged


def _env_map_for_start_env(start_env: str):
    """按 start env 合并 .env 配置并返回字典。"""
    if start_env == "dev":
        return _merge_dotenv_files(".env", ".env.development")
    if start_env == "prod":
        return _merge_dotenv_files(".env", ".env.production")
    raise ValueError("env 只能是 dev 或 prod")


def _pymysql_connect_kw_for_start_env(start_env: str):
    """start 入参 env 为 dev|prod：用 .env + 对应环境文件的 DB_PORT 等连接数据库。"""
    m = _env_map_for_start_env(start_env)

    def pick(key, default=None):
        if key in m and m[key] is not None:
            return m[key]
        return os.getenv(key, default)

    port_s = pick("DB_PORT", "3306")
    try:
        port = int(port_s)
    except (TypeError, ValueError):
        port = 3306
    return {
        "host": pick("DB_HOST", "127.0.0.1"),
        "port": port,
        "user": pick("DB_USER", "root"),
        "password": pick("DB_PASSWORD", "") or "",
        "database": pick("DB_NAME", "media_operator"),
        "charset": "utf8mb4",
    }


def _download_path_for_start_env(start_env: str):
    """读取下载目录（.env + 环境专用 .env），默认 /Users/wilson/Movies/service-stt-download。"""
    m = _env_map_for_start_env(start_env)
    path = (m.get("DOWNLOAD_PATH") or os.getenv("DOWNLOAD_PATH") or "/Users/wilson/Movies/service-stt-download").strip()
    if not path:
        path = "/Users/wilson/Movies/service-stt-download"
    return path


def _download_timeout_sec_for_start_env(start_env: str):
    """读取下载超时秒数，默认 900 秒。"""
    m = _env_map_for_start_env(start_env)
    raw = (m.get("DOWNLOAD_TIMEOUT_SEC") or os.getenv("DOWNLOAD_TIMEOUT_SEC") or "900").strip()
    try:
        sec = int(raw)
    except (TypeError, ValueError):
        sec = 900
    return max(sec, 10)


def _record_stop_to_db(db_kw: dict, env_label: str, reason: str):
    """将停止原因写入当前任务使用的数据库（表 stt_stop_log，见 schema/table.sql）。"""
    table = os.getenv("STT_STOP_LOG_TABLE", "stt_stop_log").strip() or "stt_stop_log"
    safe_table = "".join(c for c in table if c.isalnum() or c == "_")
    if safe_table != table:
        raise ValueError("STT_STOP_LOG_TABLE 仅允许字母数字下划线")
    kw = {k: v for k, v in db_kw.items() if k in ("host", "port", "user", "password", "database", "charset")}
    conn = pymysql.connect(**kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO `{safe_table}` (env, reason, add_ts) VALUES (%s, %s, %s)",
                (env_label or "", reason[:512], int(time.time() * 1000)),
            )
        conn.commit()
    finally:
        conn.close()


def _trigger_download_via_applescript(video_url: str):
    """通过 AppleScript 触发 Downie 4 下载。"""
    if sys.platform != "darwin":
        raise RuntimeError("当前系统非 macOS，无法通过 AppleScript 控制 Downie 4")
    if not video_url:
        raise ValueError("video_url 不能为空")
    script = (
        "on run argv\n"
        "set video_url to item 1 of argv\n"
        'tell application "Downie 4" to activate\n'
        'do shell script "open -a " & quoted form of "Downie 4" & " " & quoted form of video_url\n'
        "end run"
    )
    rs = subprocess.run(
        ["osascript", "-e", script, "--", video_url],
        capture_output=True,
        text=True,
        check=False,
    )
    if rs.returncode != 0:
        err = (rs.stderr or rs.stdout or "").strip() or "unknown error"
        raise RuntimeError(f"AppleScript 触发下载失败: {err}")
    print(f"[start] AppleScript 已触发下载, url={video_url}")


def _wait_downie_download(download_path: str, download_id: str, timeout_sec: int = 900):
    """
    监控 Downie 下载目录，返回 (video_path, meta_json_path, srt_path_or_none)。
    判定规则：
    - 下载中：存在 *-{download_id}.downiepart
    - 下载完成：存在 *-{download_id}.mp4 且 *-{download_id}.json
    """
    os.makedirs(download_path, exist_ok=True)
    # 严格匹配：<任意标题>-<download_id>.<ext>
    filename_re = re.compile(
        rf"^.+-{re.escape(str(download_id))}\.(downiepart|mp4|json|srt)$",
        re.IGNORECASE,
    )
    deadline = time.time() + max(timeout_sec, 10)
    seen_any = False
    last_state = None
    while True:
        if getattr(cfg, "STOP_START", False):
            raise RuntimeError("下载监控被停止")
        if time.time() > deadline:
            raise TimeoutError(f"等待 Downie 下载超时: download_id={download_id}")
        try:
            names = os.listdir(download_path)
        except FileNotFoundError:
            names = []
        mp4_name = None
        json_name = None
        srt_name = None
        downloading = False
        downiepart_name = None
        matched_count = 0
        for name in names:
            m = filename_re.match(name)
            if not m:
                continue
            seen_any = True
            matched_count += 1
            ext = m.group(1).lower()
            if ext == "downiepart":
                downloading = True
                downiepart_name = name
            elif ext == "mp4":
                mp4_name = name
            elif ext == "json":
                json_name = name
            elif ext == "srt":
                srt_name = name
        cur_state = (bool(seen_any), matched_count, bool(downloading), mp4_name or "", json_name or "", srt_name or "", downiepart_name or "")
        if cur_state != last_state:
            print(
                f"[start] download_id={download_id} 监控状态 "
                f"count={matched_count} "
                f"downloading={downloading} "
                f"downiepart={downiepart_name or '-'} "
                f"mp4={mp4_name or '-'} json={json_name or '-'} srt={srt_name or '-'}"
            )
            last_state = cur_state
        # 文件先出现又全部消失：按需求判定为下载失败。
        if seen_any and matched_count == 0:
            raise RuntimeError(f"download_id={download_id} 文件已消失，判定下载失败")
        # 3个文件：mp4 + json + srt => 下载成功且有字幕
        if (not downloading) and mp4_name and json_name and srt_name and matched_count >= 3:
            print(
                f"[start] download_id={download_id} 下载完成(有字幕) "
                f"mp4={mp4_name} json={json_name} srt={srt_name or '-'}"
            )
            return (
                os.path.join(download_path, mp4_name),
                os.path.join(download_path, json_name),
                os.path.join(download_path, srt_name) if srt_name else None,
            )
        # 2个文件：mp4 + json => 下载成功无字幕
        if (not downloading) and mp4_name and json_name and (not srt_name) and matched_count >= 2:
            print(
                f"[start] download_id={download_id} 下载完成(无字幕) "
                f"mp4={mp4_name} json={json_name}"
            )
            return (
                os.path.join(download_path, mp4_name),
                os.path.join(download_path, json_name),
                None,
            )
        # 固定每 5 秒轮询
        time.sleep(5)


def _video_to_wav_for_stt(video_path: str):
    """将视频转为 16k 单声道 wav，返回 wav 路径。"""
    wav_path = video_path + ".stt.wav"
    rs = tool.runffmpeg(["-i", video_path, "-ar", "16000", "-ac", "1", "-y", wav_path])
    if rs != "ok":
        raise RuntimeError(f"ffmpeg 转音频失败: {rs}")
    if not os.path.isfile(wav_path):
        raise RuntimeError("ffmpeg 未生成 wav 文件")
    return wav_path


def _run_start_task(start_env: str):
    """实际执行 /start 新流程：Downie 下载监控 + 字幕优先 + 无字幕 STT。"""
    db_kw = _pymysql_connect_kw_for_start_env(start_env)
    download_path = _download_path_for_start_env(start_env)
    download_timeout_sec = _download_timeout_sec_for_start_env(start_env)
    print(
        "[start] 当前数据库配置 (env=%s):" % start_env,
        f"host={db_kw['host']} port={db_kw['port']} user={db_kw['user']} password=**** database={db_kw['database']}",
    )
    print("[start] 下载目录:", download_path)
    print("[start] 下载超时(秒):", download_timeout_sec)
    cfg.START_RUNNING = True
    cfg.STOP_START = False
    conn = None
    try:
        conn = pymysql.connect(
            **db_kw,
            cursorclass=DictCursor,
        )
    except Exception as e:
        cfg.START_RUNNING = False
        cfg.START_TASK_DB_KWARGS = None
        cfg.START_TASK_ENV_LABEL = None
        cfg.LAST_ERROR_MSG = str(e)
        app.logger.error(f"[start] 数据库连接失败: {e}")
        raise

    processed = 0
    last_data = None
    try:
        while True:
            # 若收到停止指令，则退出循环
            if getattr(cfg, "STOP_START", False):
                cfg.STOP_START = False
                print("[start] 收到停止指令，已停止任务，processed =", processed)
                break

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bilibili_video WHERE is_deleted = 0 AND status = 0 AND locked = 0 ORDER BY priority DESC LIMIT 1"
                )
                row = cur.fetchone()
            if not row:
                print("[start] 没有待处理的 bilibili_video 记录，已结束任务，processed =", processed)
                break

            row_id = row["id"]
            # 先将记录置为 locked=1，避免并发重复处理
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE bilibili_video SET locked = 1 WHERE id = %s AND locked = 0",
                    (row_id,),
                )
                conn.commit()
                if cur.rowcount != 1:
                    # 该记录已被其他任务锁定，跳过继续取下一条
                    continue

            download_id = str((row.get("download_id") or "")).strip()
            # Downie 触发下载必须使用视频页地址（如 bilibili.com/video/BV...）
            video_url = (row.get("video_url") or "").strip()
            if not download_id:
                err_msg = "该条记录缺少 download_id"
                cfg.LAST_ERROR_MSG = err_msg
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE bilibili_video SET status = -1, remark = %s WHERE id = %s",
                        (err_msg, row_id),
                    )
                    conn.commit()
                continue
            if not video_url:
                err_msg = "该条记录无 video_url"
                cfg.LAST_ERROR_MSG = err_msg
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE bilibili_video SET status = -1, remark = %s WHERE id = %s",
                        (err_msg, row_id),
                    )
                    conn.commit()
                # 跳过当前记录，继续处理下一条
                continue

            wav_path = None
            try:
                _trigger_download_via_applescript(video_url)
                video_path, meta_path, srt_path = _wait_downie_download(
                    download_path, download_id, timeout_sec=download_timeout_sec
                )
                text = ""
                if srt_path and os.path.isfile(srt_path):
                    with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = (f.read() or "").strip()
                    print(f"[start] download_id={download_id} 命中字幕文件，直接入库: {srt_path}")
                else:
                    wav_path = _video_to_wav_for_stt(video_path)
                    text = _api_process(
                        model_name="small", wav_file=wav_path, language="zh", response_format="text"
                    )
                    if not (isinstance(text, str) and text.strip()):
                        text = ""
                    print(f"[start] download_id={download_id} 未命中字幕，已走语音识别。meta={meta_path}")
                # 成功：写回 context，清空下载地址，status=1
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE bilibili_video SET context = %s, audio_download_url = NULL, video_download_url = NULL, status = 1, locked = 0 WHERE id = %s",
                        (text.strip(), row_id),
                    )
                    conn.commit()
                data = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
                data["context"] = text.strip()
                data["audio_download_url"] = None
                data["video_download_url"] = None
                data["status"] = 1
                data["locked"] = 0
                last_data = data
                processed += 1
                print(
                    "[start] bilibili_video 一条记录已写回 context，已清空下载地址，status=1，累计处理:",
                    processed,
                )
            except Exception as inner_e:
                err_msg = str(inner_e)[:512]
                cfg.LAST_ERROR_MSG = err_msg
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE bilibili_video SET status = -1, remark = %s, locked = 1 WHERE id = %s",
                        (err_msg, row_id),
                    )
                    conn.commit()
                app.logger.error(f"[start] error: {inner_e}")
                # 跳过当前记录，继续处理下一条
                continue
            finally:
                # 无论成功或失败，删除临时 wav 文件
                if wav_path and os.path.isfile(wav_path):
                    try:
                        os.remove(wav_path)
                        print("[start] 已删除临时 wav:", wav_path)
                    except OSError:
                        pass
    finally:
        cfg.START_RUNNING = False
        cfg.START_TASK_DB_KWARGS = None
        cfg.START_TASK_ENV_LABEL = None
        if conn is not None:
            conn.close()


def _open_downie4_via_applescript():
    """在 macOS 上通过 AppleScript 激活 Downie 4。"""
    if sys.platform != "darwin":
        return
    script = 'tell application "Downie 4" to activate'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        app.logger.warning(f"[boot] 打开 Downie 4 失败: {e}")


@app.route('/start', methods=['POST'])
def start():
    """触发 bilibili_video 批量处理任务（仅新流程），立即返回，不等待解析完成。"""
    try:
        body = request.get_json(silent=True) or {}
        table = request.form.get("table") or body.get("table")
        start_env = (request.form.get("env") or body.get("env") or "").strip().lower()
        if not table:
            return jsonify({"code": 500, "message": "缺少参数 table"}), 500
        if table != "bilibili_video":
            return jsonify({"code": 500, "message": f"暂不支持表: {table}"}), 500
        if start_env not in ("dev", "prod"):
            return jsonify({"code": 500, "message": "参数 env 只能是 dev 或 prod"}), 500
        # 若已在运行，则直接返回
        if getattr(cfg, "START_RUNNING", False):
            return jsonify({"code": 200, "message": "任务已在运行中"}), 200
        try:
            _pre_kw = _pymysql_connect_kw_for_start_env(start_env)
        except Exception as e:
            return jsonify({"code": 500, "message": str(e)}), 500
        cfg.START_TASK_DB_KWARGS = {k: v for k, v in _pre_kw.items()}
        cfg.START_TASK_ENV_LABEL = start_env
        # 后台启动任务线程（仅 Downie 新流程，与上方 DB 配置一致，供 /start/stop 写入同一库）
        t = threading.Thread(target=_run_start_task, args=(start_env,), daemon=True)
        t.start()
        return jsonify({"code": 200, "message": "任务已启动（Downie 新流程）"}), 200
    except Exception as e:
        cfg.LAST_ERROR_MSG = str(e)
        app.logger.error(f"[start] error: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route('/last_error', methods=['GET'])
def last_error():
    """获取上一次 /start 执行时的错误原因（进程级内存记录）。"""
    return jsonify({"code": 200, "message": "ok", "data": getattr(cfg, "LAST_ERROR_MSG", "")}), 200


@app.route('/start/stop', methods=['POST'])
def stop_start():
    """标记停止 /start 任务的继续执行。仅影响当前进程内的后续循环。"""
    try:
        db_kw = getattr(cfg, "START_TASK_DB_KWARGS", None)
        env_label = getattr(cfg, "START_TASK_ENV_LABEL", None) or ""
        reason = "STT 批量任务：用户调用 /start/stop 请求停止"
        cfg.STOP_START = True
        if db_kw:
            try:
                _record_stop_to_db(db_kw, env_label, reason)
            except Exception as log_e:
                app.logger.warning(f"[start/stop] 写入 stt_stop_log 失败（可忽略或先执行建表 SQL）: {log_e}")
        cfg.LAST_STOP_MESSAGE = reason
        return jsonify({"code": 200, "message": "stop signal sent"}), 200
    except Exception as e:
        cfg.LAST_ERROR_MSG = str(e)
        app.logger.error(f"[start/stop] error: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route('/start/status', methods=['GET'])
def start_status():
    """查询 /start 任务是否正在执行。"""
    try:
        running = bool(getattr(cfg, "START_RUNNING", False))
        return jsonify({
            "code": 200,
            "message": "running" if running else "not running",
            "data": {
                "running": running
            }
        }), 200
    except Exception as e:
        cfg.LAST_ERROR_MSG = str(e)
        app.logger.error(f"[start/status] error: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route('/checkupdate', methods=['GET', 'POST'])
def checkupdate():
    return jsonify({'code': 0, "msg": cfg.updatetips})


if __name__ == '__main__':
    _parser = argparse.ArgumentParser(description="service-stt")
    _parser.add_argument(
        "--http-addr",
        dest="http_addr",
        default=None,
        metavar="HOST:PORT",
        help="监听地址，覆盖本进程内 set.ini / 环境变量推导的端口（如 0.0.0.0:9988）",
    )
    _args, _unknown = _parser.parse_known_args()
    if _args.http_addr:
        _addr = _args.http_addr.strip()
        if ":" not in _addr:
            print("error: --http-addr 需为 HOST:PORT，例如 0.0.0.0:9988", file=sys.stderr)
            sys.exit(1)
        _host_part, _port_part = _addr.rsplit(":", 1)
        if not _host_part or not _port_part.isdigit():
            print("error: --http-addr 格式无效，例如 0.0.0.0:9988", file=sys.stderr)
            sys.exit(1)
        cfg.web_address = _addr
        print(f"[boot] 使用 --http-addr 监听: {cfg.web_address}")

    http_server = None
    try:
        threading.Thread(target=tool.checkupdate).start()
        threading.Thread(target=shibie).start()
        try:
            if cfg.devtype=='cpu':
                print('\n如果设备使用英伟达显卡并且CUDA环境已正确安装，可修改set.ini中\ndevtype=cpu 为 devtype=cuda, 然后重新启动以加快识别速度\n')
            host = cfg.web_address.rsplit(":", 1)
            http_server = WSGIServer((host[0], int(host[1])), app, handler_class=CustomRequestHandler)
            # 根据环境变量控制是否打开浏览器，默认打开
            if os.getenv("START_OPEN_WEB", "1") == "1":
                threading.Thread(target=tool.openweb, args=(cfg.web_address,)).start()
            # 根据环境变量控制是否联动打开 Downie 4（默认关闭，主流程使用 ssh 命令触发下载）
            if os.getenv("START_OPEN_DOWNIE4", "0") == "1":
                threading.Thread(target=_open_downie4_via_applescript, daemon=True).start()
            http_server.serve_forever()
        finally:
            if http_server:
                http_server.stop()
    except Exception as e:
        if http_server:
            http_server.stop()
        print("error:" + str(e))
        app.logger.error(f"[app]start error:{str(e)}")
