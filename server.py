from flask import Flask, request, jsonify
from mcrcon import MCRcon
import sqlite3
import bcrypt
import json
from datetime import datetime
import threading
import time

app = Flask(__name__, static_folder='.', static_url_path='')

# RCON配置
RCON_HOST = 'localhost'
RCON_PORT = 25575
RCON_PASSWORD = '123456'

# EasyAuth数据库路径
EASYAUTH_DB = r'D:\PCL\MC_Server_26.2\EasyAuth\easyauth.db'

# 服务器心跳记录
last_heartbeat = None
server_online = False

# 定期检查RCON的线程
def check_server():
    global last_heartbeat, server_online
    while True:
        try:
            with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT, timeout=2) as mcr:
                mcr.command('list')
                server_online = True
                last_heartbeat = datetime.now()
        except:
            server_online = False
        time.sleep(30)  # 每30秒检查一次

# 启动检查线程
threading.Thread(target=check_server, daemon=True).start()

# 服务器心跳记录
last_heartbeat = None

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    global last_heartbeat
    last_heartbeat = datetime.now()
    return jsonify({'success': True})

@app.route('/api/server_status')
def server_status():
    global last_heartbeat, server_online
    
    # 判断状态
    if server_online:
        status = 'online'
        message = '服务器在线'
    else:
        # 服务器离线，检查最后心跳时间
        if last_heartbeat:
            time_diff = (datetime.now() - last_heartbeat).total_seconds()
            if time_diff < 120:  # 2分钟内还有心跳，说明是正常关闭
                status = 'normal_offline'
                message = '服务器离线'
            else:  # 超过2分钟没心跳，说明是异常关闭
                status = 'crash'
                message = '服务器可能脱机，请立即联系管理员'
        else:
            status = 'unknown'
            message = '服务器离线'
    
    return jsonify({
        'status': status,
        'message': message,
        'last_heartbeat': last_heartbeat.isoformat() if last_heartbeat else None
    })

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    player_name = data.get('name')
    password = data.get('password')
    
    if not player_name or not password:
        return jsonify({'success': False, 'message': '请输入用户名和密码'})
    
    # 读取EasyAuth数据库
    conn = sqlite3.connect(EASYAUTH_DB)
    c = conn.cursor()
    c.execute('SELECT * FROM easyauth WHERE username_lower = ?', (player_name.lower(),))
    player = c.fetchone()
    conn.close()
    
    if not player:
        return jsonify({'success': False, 'message': '用户不存在，请先注册'})
    
    # 解析data字段
    player_data = json.loads(player[5])
    hashed_password = player_data.get('password', '')
    
    if not hashed_password:
        return jsonify({'success': False, 'message': '用户未注册密码'})
    
    # 验证密码
    if bcrypt.checkpw(password.encode(), hashed_password.encode()):
        return jsonify({
            'success': True,
            'message': f'登录成功，欢迎回来 {player_name}！'
        })
    else:
        return jsonify({'success': False, 'message': '密码错误'})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    player_name = data.get('name')
    password = data.get('password')
    
    if not player_name or not password:
        return jsonify({'success': False, 'message': '请输入用户名和密码'})
    
    if len(password) < 3:
        return jsonify({'success': False, 'message': '密码至少3位'})
    
    # 检查用户是否已存在
    conn = sqlite3.connect(EASYAUTH_DB)
    c = conn.cursor()
    c.execute('SELECT * FROM easyauth WHERE username_lower = ?', (player_name.lower(),))
    player = c.fetchone()
    
    if player:
        conn.close()
        return jsonify({'success': False, 'message': '用户已存在，请直接登录'})
    
    # 加密密码
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    
    # 插入新用户
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.0000000+08:00[Asia/Shanghai]')
    player_data = json.dumps({
        "password": hashed,
        "last_ip": "",
        "last_authenticated_date": "1970-01-01T00:00:00Z",
        "login_tries": 0,
        "last_kicked_date": "1970-01-01T00:00:00Z",
        "online_account": "UNKNOWN",
        "registration_date": now,
        "data_version": 1
    })
    
    c.execute('INSERT INTO easyauth (username, username_lower, uuid, last_ip, data) VALUES (?, ?, NULL, "", ?)',
              (player_name, player_name.lower(), player_data))
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'注册成功！现在可以在游戏里用 /login {password} 登录了'
    })

@app.route('/api/claim_reward', methods=['POST'])
def claim_reward():
    data = request.json
    player_name = data.get('name')
    
    if not player_name:
        return jsonify({'success': False, 'message': '请输入玩家名称'})
    
    # 给玩家发奖励（通过RCON）
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command(f'give {player_name} minecraft:bread 16')
            mcr.command(f'give {player_name} minecraft:iron_pickaxe')
            mcr.command(f'give {player_name} minecraft:iron_sword')
            mcr.command(f'give {player_name} minecraft:torch 32')
    except Exception as e:
        print(f"RCON错误: {e}")
    
    return jsonify({
        'success': True,
        'message': f'新手奖励已发放给 {player_name}！'
    })

# 管理员申请存储
admin_applications = []

@app.route('/api/admin_application', methods=['POST'])
def admin_application():
    data = request.json
    name = data.get('name')
    time_played = data.get('time')
    reason = data.get('reason')
    online_time = data.get('online')
    
    if not name or not time_played or not reason or not online_time:
        return jsonify({'success': False, 'message': '请填写完整'})
    
    # 检查玩家是否被ban过
    ban_status = '无记录'
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT, timeout=2) as mcr:
            # 检查封禁列表
            resp = mcr.command(f'banlist')
            if name in resp:
                ban_status = '曾被封禁'
    except:
        pass
    
    # 保存申请
    application = {
        'name': name,
        'time_played': time_played,
        'reason': reason,
        'online_time': online_time,
        'ban_status': ban_status,
        'status': '待审核'
    }
    admin_applications.append(application)
    
    print(f"新的管理员申请: {name}")
    print(f"封禁状态: {ban_status}")
    
    return jsonify({
        'success': True,
        'message': f'申请提交成功！我们会尽快审核，封禁记录: {ban_status}'
    })

@app.route('/api/admin_applications')
def get_admin_applications():
    return jsonify(admin_applications)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
