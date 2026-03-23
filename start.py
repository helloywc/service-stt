import logging,shutil
import re
import threading
import sys
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
import yt_dlp

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


def _download_bilibili_audio(video_url, cookies_str, out_dir, video_id):
    """用 yt-dlp 下载 B 站视频音频到 out_dir，转为 16k 单声道 wav，返回 wav 文件路径。"""
    safe_id = re.sub(r"[^\w\-]", "_", str(video_id))[:64]
    out_tmpl = os.path.join(out_dir, f"{safe_id}_audio.%(ext)s")
    wav_path = os.path.join(out_dir, f"{safe_id}_audio.wav")
    opts = {
        "outtmpl": out_tmpl,
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": None}
        ],
    }
    if cookies_str:
        opts["http_headers"] = {"Cookie": cookies_str}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video_url])
    if not os.path.isfile(wav_path):
        raise RuntimeError("yt-dlp 未生成 wav 文件")
    # 转为 16k 单声道供 whisper
    rs = tool.runffmpeg(["-i", wav_path, "-ar", "16000", "-ac", "1", "-y", wav_path + ".16k.wav"])
    if rs != "ok":
        raise RuntimeError(f"ffmpeg 转码失败: {rs}")
    os.replace(wav_path + ".16k.wav", wav_path)
    return wav_path


def _run_start_task(platform: str):
    """实际执行 bilibili_video 批量处理任务的后台函数。"""
    print(
        "[start] 当前数据库配置:",
        f"host={cfg.DB_HOST} port={cfg.DB_PORT} user={cfg.DB_USER} password=**** database={cfg.DB_NAME}",
    )
    cfg.START_RUNNING = True
    cfg.STOP_START = False
    conn = pymysql.connect(
            host=cfg.DB_HOST,
            port=cfg.DB_PORT,
            user=cfg.DB_USER,
            password=cfg.DB_PASSWORD,
            database=cfg.DB_NAME,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
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

            video_id = row.get("video_id") or row.get("bvid") or row.get("id")
            video_url = (
                row.get("video_url")
                or row.get("video_download_url")
                or row.get("audio_download_url")
                or ""
            ).strip()
            if not video_url:
                err_msg = "该条记录无视频/音频地址"
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
                # 从 crawler_cookies_account 取 platform 对应 cookies
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT cookies FROM crawler_cookies_account WHERE platform_name = %s AND is_deleted = 0 AND status = 0 ORDER BY priority DESC LIMIT 1",
                        (platform,),
                    )
                    acc = cur.fetchone()
                cookies_str = _cookies_header_from_db(acc["cookies"]) if acc and acc.get("cookies") else None
                # 下载音频到 static/tmp
                wav_path = _download_bilibili_audio(video_url, cookies_str, cfg.TMP_DIR, video_id)
                # 调用本地转写：语言 zh，模型 small
                text = _api_process(
                    model_name="small", wav_file=wav_path, language="zh", response_format="text"
                )
                if not (isinstance(text, str) and text.strip()):
                    text = ""
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
                # 无论成功或失败，删除已下载的音频文件
                if wav_path and os.path.isfile(wav_path):
                    try:
                        os.remove(wav_path)
                        print("[start] 已删除临时音频:", wav_path)
                    except OSError:
                        pass
    finally:
        cfg.START_RUNNING = False
        conn.close()


@app.route('/start', methods=['POST'])
def start():
    """触发 bilibili_video 批量处理任务，立即返回，不等待解析完成。"""
    try:
        body = request.get_json(silent=True) or {}
        table = request.form.get("table") or body.get("table")
        platform = request.form.get("platform") or body.get("platform") or "bili"
        if not table:
            return jsonify({"code": 500, "message": "缺少参数 table"}), 500
        if table != "bilibili_video":
            return jsonify({"code": 500, "message": f"暂不支持表: {table}"}), 500
        # 若已在运行，则直接返回
        if getattr(cfg, "START_RUNNING", False):
            return jsonify({"code": 200, "message": "任务已在运行中"}), 200
        # 后台启动任务线程
        t = threading.Thread(target=_run_start_task, args=(platform,), daemon=True)
        t.start()
        return jsonify({"code": 200, "message": "任务已启动"}), 200
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
        cfg.STOP_START = True
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
    http_server = None
    try:
        threading.Thread(target=tool.checkupdate).start()
        threading.Thread(target=shibie).start()
        try:
            if cfg.devtype=='cpu':
                print('\n如果设备使用英伟达显卡并且CUDA环境已正确安装，可修改set.ini中\ndevtype=cpu 为 devtype=cuda, 然后重新启动以加快识别速度\n')
            host = cfg.web_address.split(':')
            http_server = WSGIServer((host[0], int(host[1])), app, handler_class=CustomRequestHandler)
            # 根据环境变量控制是否打开浏览器，默认打开
            if os.getenv("START_OPEN_WEB", "1") == "1":
                threading.Thread(target=tool.openweb, args=(cfg.web_address,)).start()
            http_server.serve_forever()
        finally:
            if http_server:
                http_server.stop()
    except Exception as e:
        if http_server:
            http_server.stop()
        print("error:" + str(e))
        app.logger.error(f"[app]start error:{str(e)}")
