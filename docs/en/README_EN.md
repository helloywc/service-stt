<div align="center">

[中文简体](../../README.md) | **English** | [Português (Brasil)](../pt/README_pt-BR.md)

</div>

---

<div align="center">

[👑 Support the project](https://github.com/jianchang512/pyvideotrans/blob/main/docs/about.md) | [Discord](https://discord.gg/SyT6GEwkJS)

</div>

---

# Voice Recognition to Text Tool

This is an offline local voice recognition tool to text, based on the open-source model fast-whisper. It can recognize and convert human voice in videos/audios into text, in json format, srt subtitle with timestamps format, and plain text format. It can be used after self-deployment to replace the voice recognition interface of openai or Baidu Voice Recognition, etc. The accuracy is basically the same as the official api interface of openai.

> 
> After deployment or download, double click on start.exe to automatically call the local browser to open the local webpage.
>
> Drag or click to select the audio and video file to be recognized, then select the speaking language, output text format, model used (base model built-in), click start recognition, after completion, output in the selected format on the current webpage.
>
> The entire process does not require the internet, it operates entirely locally, and can be deployed on the intranet.
>
> The fast-whisper open-source model has base/small/medium/large-v3, with built-in base model, base->large-v3 recognition effect is getting better and better, but the computer resources required are also more, you can download and unzip it into the models directory according to need.
>
> [All model download links](https://github.com/jianchang512/stt/releases/tag/0.0)
>


# Video Demonstration


https://github.com/jianchang512/stt/assets/3378335/d716acb6-c20c-4174-9620-f574a7ff095d


![image](https://github.com/jianchang512/stt/assets/3378335/0f724ff1-21b3-4960-b6ba-5aa994ea414c)




# Precompiled Win Version Usage Method / Linux and Mac Source Code Deployment

1. [Click here to go to the Releases page to download](https://github.com/jianchang512/stt/releases) precompiled file

2. After downloading, unzip it somewhere, such as E:/stt

3. Double-click start.exe, and wait for the browser window to open automatically

4. Click on the upload area on the page, find the audio or video file you want to recognize in the pop-up window, or directly drag the audio and video file to the upload area, then select the spoken language, text output format, and model used, click "Start Recognition Immediately", wait for a while, the text boxes at the bottom will display the recognition results in the selected format

5. If the computer has an Nvidia GPU and the CUDA environment is correctly configured, CUDA acceleration will be used automatically


# Source Code Deployment (Linux / Mac / Window)

- Requires Python 3.9–3.11. Use [uv](https://docs.astral.sh/uv/) for dependency management and running (no manual venv needed).

1. Install uv: <https://docs.astral.sh/uv/getting-started/installation/>

2. Clone the repo and enter the project directory, e.g. `git clone git@github.com:jianchang512/stt.git .`

3. Install dependencies: `uv sync` (or `make install`)

4. Start the service (choose one):
   - **make:** `make run`
   - **Windows:** double-click `run.bat` or run `uv run python start.py`
   - **Linux / Mac:** `./run.sh` or `uv run python start.py`

5. For CUDA acceleration, after first run execute:
   ```bash
   uv pip uninstall torch
   uv pip install torch --index-url https://download.pytorch.org/whl/cu121
   ```

6. Windows: put `ffmpeg.exe` and `ffprobe.exe` in the project directory. Linux/Mac: install ffmpeg from the [ffmpeg official website](https://ffmpeg.org/download.html) and ensure `ffmpeg`/`ffprobe` are on PATH or in the project root.

7. [Download the model package](https://github.com/jianchang512/stt/releases/tag/0.0) and put the extracted folders into the project root’s `models` folder.

8. After starting, wait for the local browser window to open automatically.




# API Interface

Interface address: http://127.0.0.1:9977/api

Request method: POST

Request parameters:

    language: Language code: optional below

    >
    > Chinese: zh
    > English: en
    > French: fr
    > German: de
    > Japanese: ja
    > Korean: ko
    > Russian: ru
    > Spanish: es
    > Thai: th
    > Italian: it
    > Portuguese: pt
    > Vietnamese: vi
    > Arabic: ar
    > Turkish: tr
    >

    model: Model name, optional below
    >
    > base corresponds to models/models--Systran--faster-whisper-base
    > small corresponds to models/models--Systran--faster-whisper-small
    > medium corresponds to models/models--Systran--faster-whisper-medium
    > large-v3 corresponds to models/models--Systran--faster-whisper-large-v3
    >

    response_format: the returned subtitle format. Can be text|json|srt

    file: audio and video files, binary upload

Api request example

```python
    import requests
    # Request address
    url = "http://127.0.0.1:9977/api"
    # Request parameters include file: audio and video files, language: language code, model: model, response_format: text|json|srt
    # Returns code==0 success, others fail, msg==success is ok, others fail reasons, data=returned text after recognition
    files = {"file": open("C:\\Users\\c1\\Videos\\2.wav", "rb")}
    data={"language":"zh","model":"base","response_format":"json"}
    response = requests.request("POST", url, timeout=600, data=data,files=files)
    print(response.json())
```



# CUDA Acceleration Support

**Install CUDA Tools** [Detailed installation method](https://juejin.cn/post/7318704408727519270)

If your computer has Nvidia graphics card, first upgrade the graphics card driver to the latest, and then to install the corresponding 
   [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)  and  [cudnn for CUDA11.X](https://developer.nvidia.com/rdp/cudnn-archive).
   
   After the installation is completed, press `Win + R`, type `cmd` and then press enter. In the pop-up window, type `nvcc --version`, confirm that there is version information displayed, similar to the graphic shown
   ![Image](https://github.com/jianchang512/pyvideotrans/assets/3378335/e68de07f-4bb1-4fc9-bccd-8f841825915a)

   Then continue typing `nvidia-smi`, confirm there is output info and you can see the cuda version number, similar to the graphic shown
   ![Image](https://github.com/jianchang512/pyvideotrans/assets/3378335/71f1d7d3-07f9-4579-b310-39284734006b)

    Then execute `python testcuda.py`, if it prompts success, it means the installation is correct, otherwise please carefully check and reinstall
    By default, CPU operation is used. If you are sure to use a NVIDIA graphics card and have configured the CUDA environment, please modify the devtype=CPU in set.ini to devtype=CUDA and restart to use CUDA acceleration

# Notices

0. If you do not have Nvidia graphics card or the CUDA environment is not properly configured, do not use the large/large-v3 model, it may cause the memory to exhaust and crash
1. Chinese in some cases will output traditional characters
2. Sometimes you will encounter an error "cublasxx.dll does not exist", at this time you need to download cuBLAS, and then copy the dll file to the system directory, [click to download cuBLAS](https://github.com/jianchang512/stt/releases/download/0.0/cuBLAS_win.7z), after decompression, copy the dll file inside to C:/Windows/System32
3. By default, CPU operation is used. If you are sure to use a NVIDIA graphics card and have configured the CUDA environment, please modify the devtype=CPU in set.ini to devtype=CUDA and restart to use CUDA acceleration



# Related Projects

[Video translation dubbing tool: translate subtitles and dub](https://github.com/jianchang512/pyvideotrans)

[Voice Cloning Tool: Synthesize speech with any sound color](https://github.com/jianchang512/clone-voice)

[Vocal Background Music Separation: A very simple vocal and background music separation tool, localized webpage operation](https://github.com/jianchang512/stt)

# Acknowledgement

The other projects mainly dependent on this project are

1. https://github.com/SYSTRAN/faster-whisper
2. https://github.com/pallets/flask
3. https://ffmpeg.org/
4. https://layui.dev
