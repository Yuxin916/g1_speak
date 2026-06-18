# g1_speak

让宇树 G1 用**自己身上的喇叭**说话，并能**和人语音对话**。基于最新 `unitree_sdk2_python`,全新写的,跟旧的 `G1_Speaker`、`g1_tts_demo` 没关系。

本仓库做两件事,别搞混:

**① 给它稿子,让它照着念(单向 TTS,不对话、不联网想词)**
你提供文字,它原样念出来。适合主持、报幕、播报固定台词。

- `speak.py` —— 念你给的文字。例:`python3 speak.py --zh "各位好，欢迎来到现场"`,或 `--file script.txt` 念整篇稿子。
- 它**只念**,不会自己加话、不会回答问题。

**② 跟它对话,让它自己想词回答(听→转文字→大模型→念回复)**
你说话,它听懂后用大模型生成回复再念出来。适合问答、闲聊、语音助手。

- `talk.sh` —— 一键启动对话(自动加载 key、开麦、找麦克风),**日常用这个**。
- `chat.py` —— 对话的本体;`talk.sh` 就是包了它。也可 `python3 chat.py --text "你是谁？"` 不用麦克风、只测「大脑+喇叭」。

> 一句话:**念稿子 → `speak.py`;跟它聊 → `talk.sh`。**

## 为什么不用 SDK 自带的 TtsMaker

这台机器人**板载 TTS 引擎是坏的**:`TtsMaker()` 返回 0 但喇叭没声音(同一个服务的 LED、音量控制都正常,说明是合成那一段挂了)。

所以改成:**在 Jetson 上用 `edge-tts`(微软神经音色)合成 → 解码成 16kHz PCM → 用 `PlayStream` 推到喇叭**。这条路实测能出声,音色还更自然。

机器人**板载麦克风同样不可用**(同一个半死的 `voice` 服务),所以语音输入走**外接 USB 麦克风**——这里用的是 DJI Mic Mini 的接收器,它在 Jetson 上是一块 USB 声卡。

---

## 一、念文字:speak.py

```bash
python3 speak.py "hello this is Alex speaking"      # 英文
python3 speak.py --zh "你好，我是 G1"                # 中文
python3 speak.py --file script.txt                  # 念一个文件
python3 speak.py "faster" --voice en-US-GuyNeural --rate +15%   # 换音色/语速
```

| 参数       | 默认               | 作用                                          |
| ---------- | ------------------ | --------------------------------------------- |
| `--zh`     | 关                 | 切中文音色(等于 `--voice zh-CN-XiaoxiaoNeural`)。 |
| `--voice`  | `en-US-AriaNeural` | edge-tts 音色。全部音色:`python3 -m edge_tts --list-voices` |
| `--rate`   | `-25%`             | 语速,如 `-10%`、`+20%`。默认 `-25%`(放慢一点)。负值传参要写 `--rate=-10%`。 |
| `--volume` | `100`              | 音量 0–100。                                   |
| `--iface`  | `eth0`             | 连机器人的网卡。不确定就 `ip -br addr` 看。     |

---

## 二、对话:chat.py / talk.sh

链路:`DJI 麦克风 → Vosk 转文字 → 大模型 → speak.py 念出来`

```bash
# 一键启动(推荐):自动 source key、开麦、找麦克风
./talk.sh                      # 按键问答:按回车说话(默认录 6 秒)
./talk.sh --conversation       # 连续对话:不用按键,说完即答,Ctrl-C 退出
./talk.sh --lang en            # 英文识别
./talk.sh --stt openai         # 用云端 Whisper,中文识别准很多(联网+少量费用)

# 也可以直接调 chat.py
python3 chat.py --text "你好，你是谁？"     # 不用麦克风,测"大脑+喇叭"
python3 chat.py --audio clip.wav            # 用一个 wav 测识别
python3 chat.py --conversation --lang zh    # 连续对话
```

| 参数             | 默认     | 作用                                                                 |
| ---------------- | -------- | -------------------------------------------------------------------- |
| `--conversation` | 关       | 连续对话模式:麦克风常开,Vosk 检测到你停顿就处理,答完自动接着听。半双工(它说话时不听,避免听到自己)。 |
| `--mic`          | `auto`   | 录音设备。`auto` 按名字找 USB/DJI 声卡(卡号会变,所以不写死)。也可 `--mic plughw:2,0`。 |
| `--stt`          | `vosk`   | 识别后端。`vosk`=本地离线、低 CPU;`openai`=云端 Whisper,更准但要联网+花钱。 |
| `--lang`         | `zh`     | Vosk 语言模型:`zh` / `en` / `both`(both 两个都跑挑置信度高的,更吃 CPU;连续模式只用单语言)。 |
| `--llm`          | `openai` | 大脑后端:`openai`(默认 `gpt-4o-mini`)或 `anthropic`(Claude)。      |
| `--seconds`      | `6`      | 按键问答模式每轮录音秒数。                                            |
| `--iface`        | `eth0`   | 连机器人 DDS 的网卡。                                                 |
| `--once`         | 关       | 问答一轮就退出。                                                      |

### 为什么识别用 Vosk 而不是 Whisper

这台 Jetson(Python 3.8、ffmpeg 4.2、没 Rust、pip 很老)**装不上现代 Whisper 栈**(faster-whisper 的依赖 tokenizers 要 Rust、PyAV 要 ffmpeg≥5.0,全挂)。Vosk 有 aarch64 预编译轮子、小模型 ~40MB、**CPU 占用低**(加载 0.4s,8 秒音频识别约 3s),正合适。小中文模型识别偏糙但 GPT 多能猜对意思;想更准就 `--stt openai`,或换更大的 Vosk 中文模型(~1.3GB,更吃 CPU)。

模型放在 `models/`(不进 git):
- `vosk-model-small-cn-0.22`(中文)、`vosk-model-small-en-us-0.15`(英文)
- 下载:`https://alphacephei.com/vosk/models/`

### Key 放哪

写进 `~/.unitree_g1.env`(私有,不进 git,`chmod 600`),`talk.sh` 会自动 source:

```bash
export OPENAI_API_KEY=sk-...          # --llm openai 和/或 --stt openai 用
export ANTHROPIC_API_KEY=sk-ant-...   # --llm anthropic 用
```

> **直接跑 `chat.py` 报 `OPENAI_API_KEY not set`?** 它只读环境变量,自己不读这个文件。
> `talk.sh` 会自动 `source`,但你直接 `python3 chat.py ...` 时不会。两种解法:
>
> - 当前 shell 手动加载:`source ~/.unitree_g1.env`
> - 一劳永逸(已配置):`~/.zshrc` 末尾加 `[ -f ~/.unitree_g1.env ] && source ~/.unitree_g1.env`,以后每次登录自动加载。

`chat.py` 会按回复里有没有中文,自动选中/英文配音。

---

## 前提

- **Jetson 要联网**:edge-tts(TTS)和大模型 API 都走在线接口。
- 需要 `mpg123` 解码(已装)、`vosk`(`pip install --user vosk`,已装)。
- 外接 USB 麦克风(DJI Mic Mini 接收器)。**它的采集开关默认是静音的**——`talk.sh` 启动时会自动 `amixer ... sset Mic cap` 打开;手动持久化:`sudo alsactl store`。
- 声音只走机器人自带喇叭。

## 注意

- **没声音** —— 多半是 Jetson 没联网,edge-tts 拉不到音频。试 `curl -I https://speech.platform.bing.com`。
- **网络走错网卡** —— 这台 Jetson 的 `eth0`、`wlan0` 都在 `192.168.123.0/24`,默认路由可能挑 `wlan0` 把发给机器人的包丢掉。现象:`PlayStream` 卡住。给机器人 IP 加一条走 `eth0` 的路由即可。
- **麦克风没反应** —— ① DJI 接收器拔了/没开机/在充电,USB 声卡就消失了,`arecord -l` 看不到;② 采集开关被静音(`amixer -c <卡号> sget Mic` 看是不是 `[off]`)。卡号会变,用名字找:`arecord -l | grep -i DJI`。
- **连续模式把话切早了** —— Vosk 在你停顿时就判定说完。说整句、少停顿即可;或用按键模式 `./talk.sh`。

## SDK 怎么装的(已装好)

```bash
git clone https://github.com/unitreerobotics/unitree_sdk2_python ~/projects/unitree_sdk2_python_latest
cd ~/projects/unitree_sdk2_python_latest && pip install -e .
```
