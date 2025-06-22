from base_ctrl import BaseController
import threading
import yaml
import os
import time
from flask import Flask, jsonify
from flask_socketio import SocketIO
import os_info

# 树莓派版本检测
def is_raspberry_pi5():
    try:
        with open('/proc/cpuinfo', 'r') as file:
            for line in file:
                if 'Model' in line:
                    if 'Raspberry Pi 5' in line:
                        return True
                    else:
                        return False
    except:
        return False

# 初始化基础控制器
if is_raspberry_pi5():
    base = BaseController('/dev/ttyAMA0', 115200)
else:
    base = BaseController('/dev/serial0', 115200)

# 加载配置文件
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config_minimal.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

# 初始化OLED显示
base.base_oled(0, f["base_config"]["robot_name"])
base.base_oled(1, f"sbc_version: {f['base_config']['sbc_version']}")
base.base_oled(2, "Status Monitor")
base.base_oled(3, "Starting...")

# 创建Flask应用
app = Flask(__name__)
socketio = SocketIO(app)

# 获取系统信息
si = os_info.SystemInfo()

# 主页路由
@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>机器人状态监控</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .status-item { margin: 10px 0; padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
            .status-label { font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>机器人状态监控</h1>
        <div id="status">
            <div class="status-item">
                <span class="status-label">WiFi IP地址:</span>
                <span id="wifi-ip">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">以太网IP地址:</span>
                <span id="eth-ip">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">WiFi信号强度:</span>
                <span id="wifi-rssi">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">云台水平角度:</span>
                <span id="pan-angle">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">云台俯仰角度:</span>
                <span id="tilt-angle">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">电池电压:</span>
                <span id="voltage">获取中...</span>
            </div>
            <div class="status-item">
                <span class="status-label">运行时间:</span>
                <span id="uptime">获取中...</span>
            </div>
        </div>

        <script>
            const socket = io('/status');
            
            socket.on('update', function(data) {
                document.getElementById('wifi-ip').textContent = data.wifi_ip || '未连接';
                document.getElementById('eth-ip').textContent = data.eth_ip || '未连接';
                document.getElementById('wifi-rssi').textContent = data.wifi_rssi + ' dBm';
                document.getElementById('pan-angle').textContent = data.pan_angle + '°';
                document.getElementById('tilt-angle').textContent = data.tilt_angle + '°';
                document.getElementById('voltage').textContent = data.voltage + ' V';
                document.getElementById('uptime').textContent = data.uptime;
            });
        </script>
    </body>
    </html>
    '''

# 状态API接口
@app.route('/api/status')
def get_status():
    return jsonify({
        'wifi_ip': si.wlan_ip,
        'eth_ip': si.eth0_ip,
        'wifi_rssi': si.wifi_rssi,
        'pan_angle': getattr(base, 'pan_angle', 0),
        'tilt_angle': getattr(base, 'tilt_angle', 0),
        'voltage': base.base_data.get('v', 0)
    })

# WebSocket状态更新
def update_status_websocket():
    start_time = time.time()
    while True:
        try:
            # 计算运行时间
            elapsed_time = time.time() - start_time
            hours = int(elapsed_time // 3600)
            minutes = int((elapsed_time % 3600) // 60)
            seconds = int(elapsed_time % 60)
            uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # 准备状态数据
            status_data = {
                'wifi_ip': si.wlan_ip,
                'eth_ip': si.eth0_ip,
                'wifi_rssi': si.wifi_rssi,
                'pan_angle': getattr(base, 'pan_angle', 0),
                'tilt_angle': getattr(base, 'tilt_angle', 0),
                'voltage': base.base_data.get('v', 0),
                'uptime': uptime
            }
            
            # 发送WebSocket更新
            socketio.emit('update', status_data, namespace='/status')
            
            # 更新OLED显示
            eth0 = si.eth0_ip
            wlan = si.wlan_ip
            if eth0:
                base.base_oled(0, f"E:{eth0}")
            else:
                base.base_oled(0, "E: No Ethernet")
            if wlan:
                base.base_oled(1, f"W:{wlan}")
            else:
                base.base_oled(1, f"W: NO {si.net_interface}")
            base.base_oled(2, "Status Monitor")
            base.base_oled(3, f"{uptime} {si.wifi_rssi}dBm")
            
        except Exception as e:
            print(f"状态更新错误: {e}")
        
        time.sleep(5)

# 底层数据更新循环
def base_data_loop():
    while True:
        try:
            # 获取底层反馈数据
            feedback = base.feedback_data()
            if feedback:
                # 更新云台角度信息（如果有的话）
                if 'pan' in feedback:
                    base.pan_angle = feedback['pan']
                if 'tilt' in feedback:
                    base.tilt_angle = feedback['tilt']
        except Exception as e:
            print(f"底层数据更新错误: {e}")
        
        time.sleep(0.1)

# 启动时的初始化命令
def init_commands():
    cmd_list = [
        '{"T":142,"cmd":50}',   # 设置反馈间隔
        '{"T":131,"cmd":1}',    # 开启串口反馈
        '{"T":143,"cmd":0}',    # 关闭串口回显
    ]
    
    for cmd in cmd_list:
        try:
            base.base_json_ctrl(eval(cmd))
            print(f"执行命令: {cmd}")
            time.sleep(0.1)
        except Exception as e:
            print(f"命令执行错误: {e}")

if __name__ == "__main__":
    print("启动精简版机器人状态监控程序...")
    
    # 初始化系统信息
    si.start()
    si.resume()
    
    # 启动状态更新线程
    status_thread = threading.Thread(target=update_status_websocket, daemon=True)
    status_thread.start()
    
    # 启动底层数据更新线程
    base_thread = threading.Thread(target=base_data_loop, daemon=True)
    base_thread.start()
    
    # 执行初始化命令
    init_commands()
    
    print("程序启动完成，访问 http://localhost:5000 查看状态")
    
    # 启动Web服务器
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)