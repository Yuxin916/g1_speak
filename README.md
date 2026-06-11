# g1_speak

让宇树 G1 用**自己身上的喇叭**把文字念出来。基于最新 `unitree_sdk2_python`,全新写的,跟旧的 `G1_Speaker`、`g1_tts_demo` 没关系。

## 为什么不用 SDK 自带的 TtsMaker

这台机器人**板载 TTS 引擎是坏的**:`TtsMaker()` 返回 0 但喇叭没声音(同一个服务的 LED、音量控制都正常,说明是合成那一段挂了)。

所以改成:**在 Jetson 上用 `edge-tts`(微软神经音色)合成 → 解码成 16kHz PCM → 用 `PlayStream` 推到喇叭**。这条路实测能出声,音色还更自然。

## 怎么用

```bash
python3 speak.py "hello this is Alex speaking"      # 英文
python3 speak.py --zh "你好，我是 G1"                # 中文
python3 speak.py --file script.txt                  # 念一个文件
python3 speak.py "faster" --voice en-US-GuyNeural --rate +15%   # 换音色/语速
```

## 参数

| 参数       | 默认               | 作用                                          |
| ---------- | ------------------ | --------------------------------------------- |
| `--zh`     | 关                 | 切中文音色(等于 `--voice zh-CN-XiaoxiaoNeural`)。 |
| `--voice`  | `en-US-AriaNeural` | edge-tts 音色。全部音色:`python3 -m edge_tts --list-voices` |
| `--rate`   | `-25%`             | 语速,如 `-10%`、`+20%`。默认 `-25%`(放慢一点)。负值传参要写 `--rate=-10%`。 |
| `--volume` | `100`              | 音量 0–100。                                   |
| `--iface`  | `eth0`             | 连机器人的网卡。不确定就 `ip -br addr` 看。     |

## 前提

- **Jetson 要联网**(edge-tts 走微软在线接口)。
- 需要 `mpg123` 解码(已装)。
- 声音只走机器人自带喇叭。

## 注意

- **没声音** —— 多半是 Jetson 没联网,edge-tts 拉不到音频。试 `curl -I https://speech.platform.bing.com`。
- **网络走错网卡** —— 这台 Jetson 的 `eth0`、`wlan0` 都在 `192.168.123.0/24`,默认路由可能挑 `wlan0` 把发给机器人的包丢掉。现象:`PlayStream` 卡住。给机器人 IP 加一条走 `eth0` 的路由即可。

## SDK 怎么装的(已装好)

```bash
git clone https://github.com/unitreerobotics/unitree_sdk2_python ~/projects/unitree_sdk2_python_latest
cd ~/projects/unitree_sdk2_python_latest && pip install -e .
```
