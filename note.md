## 接口调用示例（curl）

> 基本约定：服务默认监听 `http://127.0.0.1:9977`

### 1. 异步任务启动相关

#### 1.1 启动 B 站转写任务（异步）

```bash
curl -X POST "http://127.0.0.1:9977/start" \
  -H "Content-Type: application/json" \
  -d '{
    "table": "bilibili_video",
    "platform": "bili"
  }'
```

#### 1.2 查询任务是否在运行

```bash
curl -X GET "http://127.0.0.1:9977/start/status"
```

#### 1.3 请求停止当前任务

```bash
curl -X POST "http://127.0.0.1:9977/start/stop"
```

#### 1.4 获取最近一次错误原因

```bash
curl -X GET "http://127.0.0.1:9977/last_error"
```

---

### 2. 语音识别 API（原有接口）

#### 2.1 通用 API（`/api`）

```bash
curl -X POST "http://127.0.0.1:9977/api" \
  -F "file=@/path/to/audio_or_video.wav" \
  -F "language=zh" \
  -F "model=small" \
  -F "response_format=text"
```

说明：
- `file`：音频/视频文件
- `language`：语言代码（如 `zh`、`en`）
- `model`：模型名称（如 `tiny`、`base`、`small`、`medium`、`large-v3` 等）
- `response_format`：`text` / `json` / `srt`

#### 2.2 OpenAI 兼容接口（`/v1/audio/transcriptions`）

```bash
curl -X POST "http://127.0.0.1:9977/v1/audio/transcriptions" \
  -H "Authorization: Bearer 123" \
  -F "model=small" \
  -F "language=zh" \
  -F "response_format=text" \
  -F "file=@/path/to/audio_or_video.wav"
```

返回示例（`response_format=text`）：

```json
{ "text": "转写结果..." }
```

---

### 3. Web 页面上传流程接口

#### 3.1 上传文件（`/upload`）

```bash
curl -X POST "http://127.0.0.1:9977/upload" \
  -F "audio=@/path/to/audio_or_video.mp4"
```

成功返回示例：

```json
{
  "code": 0,
  "msg": "...",
  "data": "xxx.wav"  // 存放在 static/tmp 下的文件名
}
```

#### 3.2 提交识别任务（`/process`）

```bash
curl -X POST "http://127.0.0.1:9977/process" \
  -d "wav_name=xxx.wav" \
  -d "model=small" \
  -d "language=zh" \
  -d "data_type=text"
```

参数说明：
- `wav_name`：`/upload` 返回的文件名（在 `static/tmp` 下）
- `model`：识别模型
- `language`：语言
- `data_type`：`srt` / `json` / `text`

#### 3.3 轮询进度与结果（`/progressbar`）

```bash
curl -X POST "http://127.0.0.1:9977/progressbar" \
  -d "wav_name=xxx.wav" \
  -d "model=small" \
  -d "language=zh" \
  -d "data_type=text"
```

进度完成时返回示例：

```json
{
  "code": 0,
  "data": 1.0,
  "msg": "ok",
  "result": "转写结果..."
}
```

---

### 4. 版本检查（可选）

```bash
curl -X GET "http://127.0.0.1:9977/checkupdate"
```

