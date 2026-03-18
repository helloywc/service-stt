## API 文档（curl 形式）

> 默认地址：`http://127.0.0.1:9977`
>
> 返回约定（大多数接口）：
> - **成功**：HTTP 200，`code=0`
> - **失败**：HTTP 500（或部分接口返回 400/500），`code!=0` 或 `error` 字段

---

### 1) 异步批处理任务（B站视频 → 下载音频 → 转写 → 写回 MySQL）

#### 1.1 启动任务（异步，立即返回）

- **POST** `/start`
- **Content-Type**：`application/json` 或表单
- **请求参数**
  - `table`：固定 `bilibili_video`
  - `platform`：固定/默认 `bili`（用于查询 `crawler_cookies_account.platform_name` 获取 cookies）

```bash
curl -X POST "http://127.0.0.1:9977/start" \
  -H "Content-Type: application/json" \
  -d '{
    "table": "bilibili_video",
    "platform": "bili"
  }'
```

返回示例：

```json
{ "code": 0, "msg": "任务已启动" }
```

如果已在运行中：

```json
{ "code": 0, "msg": "任务已在运行中" }
```

#### 1.2 查询任务是否正在执行

- **GET** `/start/status`

```bash
curl -X GET "http://127.0.0.1:9977/start/status"
```

返回示例：

```json
{ "code": 0, "msg": "ok", "data": { "running": true } }
```

#### 1.3 请求停止任务

- **POST** `/start/stop`
- 说明：发送停止信号，后台循环在下一轮检测到后会退出

```bash
curl -X POST "http://127.0.0.1:9977/start/stop"
```

返回示例：

```json
{ "code": 0, "msg": "stop signal sent" }
```

#### 1.4 查询最近一次错误原因（进程内存）

- **GET** `/last_error`

```bash
curl -X GET "http://127.0.0.1:9977/last_error"
```

返回示例：

```json
{ "code": 0, "msg": "ok", "data": "错误原因字符串（如无则为空）" }
```

---

### 2) 语音识别接口（上传文件直接转写）

#### 2.1 原 API（POST `/api`）

- **POST** `/api`
- **multipart/form-data**
- **参数**
  - `file`：音频/视频文件
  - `language`：如 `zh`、`en`（可选）
  - `model`：如 `tiny|base|small|medium|large-v3...`
  - `response_format`：`text|json|srt`（默认 `srt`）

```bash
curl -X POST "http://127.0.0.1:9977/api" \
  -F "file=@/path/to/audio_or_video.mp4" \
  -F "language=zh" \
  -F "model=small" \
  -F "response_format=text"
```

返回示例：

```json
{ "code": 0, "msg": "ok", "data": "转写结果..." }
```

#### 2.2 OpenAI 兼容接口（POST `/v1/audio/transcriptions`）

- **POST** `/v1/audio/transcriptions`
- **multipart/form-data**
- **参数**
  - `file`：音频/视频文件
  - `model`：模型名（同上）
  - `language`：如 `zh`
  - `prompt`：可选
  - `response_format`：`text|srt|json`（`text` 返回 `{text: ...}`；`srt` 返回纯文本；`json` 返回 json）

```bash
curl -X POST "http://127.0.0.1:9977/v1/audio/transcriptions" \
  -H "Authorization: Bearer 123" \
  -F "file=@/path/to/audio_or_video.wav" \
  -F "model=small" \
  -F "language=zh" \
  -F "response_format=text"
```

返回示例（`text`）：

```json
{ "text": "转写结果..." }
```

---

### 3) Web 页面上传/排队识别流程（分步）

#### 3.1 上传（POST `/upload`）

- **POST** `/upload`
- **multipart/form-data**
- **参数**
  - `audio`：文件字段名固定为 `audio`

```bash
curl -X POST "http://127.0.0.1:9977/upload" \
  -F "audio=@/path/to/audio_or_video.mp4"
```

返回示例（`data` 为保存到 `static/tmp` 下的文件名）：

```json
{ "code": 0, "msg": "上传成功", "data": "xxx.wav" }
```

#### 3.2 提交处理（POST `/process`）

- **POST** `/process`
- **application/x-www-form-urlencoded**
- **参数**
  - `wav_name`：`/upload` 返回的文件名
  - `model`：模型
  - `language`：语言（`auto`/`zh`/`en`...）
  - `data_type`：`srt|json|text`

```bash
curl -X POST "http://127.0.0.1:9977/process" \
  -d "wav_name=xxx.wav" \
  -d "model=small" \
  -d "language=zh" \
  -d "data_type=text"
```

返回示例：

```json
{ "code": 0, "msg": "ing" }
```

#### 3.3 查询进度与结果（POST `/progressbar`）

- **POST** `/progressbar`
- 参数与 `/process` 一致（用于定位任务 key）

```bash
curl -X POST "http://127.0.0.1:9977/progressbar" \
  -d "wav_name=xxx.wav" \
  -d "model=small" \
  -d "language=zh" \
  -d "data_type=text"
```

返回示例（完成后）：

```json
{ "code": 0, "data": 1.0, "msg": "ok", "result": "转写结果..." }
```

---

### 4) 更新检查

- **GET** `/checkupdate`

```bash
curl -X GET "http://127.0.0.1:9977/checkupdate"
```

返回示例：

```json
{ "code": 0, "msg": "" }
```

