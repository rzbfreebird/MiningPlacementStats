import json
import os
import time
import re
import uuid as uuid_lib
from typing import Dict, List, Optional, Tuple

from mcdreforged.api.all import *

PLUGIN_METADATA = {
    'id': 'mining_placement_stats',
    'version': '1.0.0',
    'name': '挖掘放置统计',
    'description': '统计玩家的挖掘榜和放置榜',
    'author': 'Fb_Rzb',
    'link': 'https://github.com/rzbfreebird/MiningPlacementStats',
    'dependencies': {
        'mcdreforged': '>=1.0.0',
    }
}

# 常量
CONFIG_FILE = 'config/mining_placement_stats.json'
STATS_FILE = 'config/mining_placement_stats_data.json'

# 默认配置
DEFAULT_CONFIG = {
    'command_prefix': '!!pls',
    'top_count': 10,
    'update_interval': 300,  # 每5分钟自动更新一次数据
    'debug': True  # 开启调试模式
}

# 数据存储
mining_stats = {}  # 格式: {玩家名: 总数量}
placement_stats = {}  # 格式: {玩家名: 总数量}
config = DEFAULT_CONFIG.copy()

# 添加以下变量到全局区域
update_thread = None
SCOREBOARD_NAME = 'stats_sidebar'

def load_config(server: PluginServerInterface):
    global config
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        save_config(server)
    server.logger.info(f'已加载配置: {config}')

def save_config(server: PluginServerInterface):
    if not os.path.exists('config'):
        os.makedirs('config')
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def load_stats(server: PluginServerInterface):
    global mining_stats, placement_stats
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            mining_stats = data.get('mining', {})
            placement_stats = data.get('placement', {})
        server.logger.info(f'已加载统计数据: 挖掘数据{len(mining_stats)}条, 放置数据{len(placement_stats)}条')
    else:
        server.logger.info('未找到现有统计数据文件，将创建新文件')
        save_stats(server)

def save_stats(server: PluginServerInterface):
    if not os.path.exists('config'):
        os.makedirs('config')
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'mining': mining_stats,
            'placement': placement_stats
        }, f, indent=4, ensure_ascii=False)

def on_load(server: PluginServerInterface, prev):
    global update_thread
    load_config(server)
    load_stats(server)
    register_commands(server)
    server.register_help_message(config['command_prefix'], '查看挖掘榜和放置榜')
    
    # 启动定时更新
    schedule_update_task(server)

def schedule_update_task(server: PluginServerInterface):
    """安排定时更新任务"""
    global update_thread
    
    def update_task():
        try:
            while True:
                time.sleep(config['update_interval'])
                update_stats_for_all_players(server)
        except Exception as e:
            server.logger.error(f"更新线程出错: {e}")
    
    update_thread = threading.Thread(target=update_task, daemon=True)
    update_thread.start()
    server.logger.info(f'已启动自动更新任务，每{config["update_interval"]}秒更新一次')

def register_commands(server: PluginServerInterface):
    server.register_command(
        Literal(config['command_prefix']).then(
            Literal('mine').runs(lambda src: show_mining_stats(server, src))
        ).then(
            Literal('place').runs(lambda src: show_placement_stats(server, src))
        ).then(
            Literal('update').runs(lambda src: update_command(server, src))
        ).then(
            Literal('debug').runs(lambda src: debug_command(server, src))
        ).then(
            Literal('help').runs(lambda src: show_help(src))
        ).runs(lambda src: show_help(src))
    )

def debug_command(server: PluginServerInterface, source: CommandSource):
    """显示调试信息"""
    if not config.get('debug', False):
        source.reply('§c调试模式未开启，请在配置文件中设置debug为true')
        return
    
    source.reply('§6§l===== 调试信息 =====')
    source.reply(f'§7当前配置: {json.dumps(config, ensure_ascii=False)}')
    source.reply(f'§7挖掘数据: {len(mining_stats)}条')
    source.reply(f'§7放置数据: {len(placement_stats)}条')
    
    # 显示服务器环境信息
    server_dir = os.path.abspath('.')
    source.reply(f'§7服务器目录: {server_dir}')
    
    # 尝试查找统计文件目录
    possible_dirs = [
        os.path.join(server_dir, 'world', 'stats'),
        os.path.join(server_dir, 'stats'),
    ]
    
    for stats_dir in possible_dirs:
        if os.path.exists(stats_dir):
            source.reply(f'§a找到统计文件目录: {stats_dir}')
            # 列出几个统计文件示例
            stats_files = os.listdir(stats_dir)[:5]  # 最多显示5个
            source.reply(f'§7统计文件示例: {", ".join(stats_files)}')
        else:
            source.reply(f'§c未找到统计文件目录: {stats_dir}')

def update_command(server: PluginServerInterface, source: CommandSource):
    """手动更新统计数据"""
    server.say('§a正在更新所有玩家的挖掘和放置统计数据...')
    updated_count = update_stats_for_all_players(server)
    server.say(f'§a数据更新完成！共更新了{updated_count}名玩家的数据')

def update_stats_for_all_players(server: PluginServerInterface) -> int:
    """更新所有玩家的统计数据"""
    server_dir = os.path.abspath('.')
    updated_count = 0
    
    # 尝试不同的统计文件目录
    stats_dirs = [
        os.path.join(server_dir, 'world', 'stats'),
        os.path.join(server_dir, 'stats'),
    ]
    
    for stats_dir in stats_dirs:
        if not os.path.exists(stats_dir):
            continue
        
        for filename in os.listdir(stats_dir):
            if not filename.endswith('.json'):
                continue
            
            # 从文件名获取UUID
            uuid = filename.split('.')[0]
            
            try:
                # 获取玩家名
                player_name = get_player_name(server, uuid)
                if not player_name:
                    continue
                
                # 读取统计数据
                with open(os.path.join(stats_dir, filename), 'r', encoding='utf-8') as f:
                    stats_data = json.load(f)
                
                # 提取挖掘数据
                mine_count = 0
                if 'stats' in stats_data and 'minecraft:mined' in stats_data['stats']:
                    for _, count in stats_data['stats']['minecraft:mined'].items():
                        mine_count += count
                
                # 提取放置数据
                place_count = 0
                if 'stats' in stats_data and 'minecraft:used' in stats_data['stats']:
                    for block_id, count in stats_data['stats']['minecraft:used'].items():
                        # 只统计方块，忽略物品
                        if ':' in block_id and not any(x in block_id for x in ['bucket', 'sword', 'axe', 'shovel', 'hoe', 'pickaxe']):
                            place_count += count
                
                # 更新数据
                mining_stats[player_name] = mine_count
                placement_stats[player_name] = place_count
                updated_count += 1
                
            except Exception as e:
                server.logger.error(f'处理玩家{uuid}的统计数据时出错: {e}')
        
        # 如果已经找到并处理了统计文件，就不再继续查找
        if updated_count > 0:
            break
    
    # 保存更新后的统计数据
    save_stats(server)
    server.logger.info(f'已更新{updated_count}名玩家的统计数据')
    return updated_count

def get_player_name(server: PluginServerInterface, uuid: str) -> Optional[str]:
    """尝试从UUID获取玩家名"""
    try:
        # 尝试执行游戏内命令获取玩家名
        result = server.execute(f'data get entity {uuid} CustomName')
        match = re.search(r'CustomName: "([^"]+)"', result)
        if match:
            return match.group(1)
        
        # 尝试从UUID缓存文件读取
        usercache_path = os.path.join(os.path.abspath('.'), 'usercache.json')
        if os.path.exists(usercache_path):
            with open(usercache_path, 'r', encoding='utf-8') as f:
                usercache = json.load(f)
                for entry in usercache:
                    if entry.get('uuid', '').replace('-', '') == uuid.replace('-', ''):
                        return entry.get('name')
        
        # 如果都失败了，直接使用UUID的一部分作为临时名称
        return f"Player_{uuid[:8]}"
    except Exception as e:
        server.logger.error(f'获取玩家{uuid}的名称时出错: {e}')
        return None

def show_mining_stats(server: PluginServerInterface, source: CommandSource):
    """显示挖掘榜"""
    count = config.get('top_count', 10)
    
    if not mining_stats:
        server.say('§c还没有挖掘数据，请先挖掘一些方块')
        return
    
    sorted_stats = sorted(mining_stats.items(), key=lambda x: x[1], reverse=True)
    
    # 使用server.say向所有玩家广播消息
    server.say('§6§l===== 挖掘榜 - 前{}名 ====='.format(min(count, len(sorted_stats))))
    for i, (player, total) in enumerate(sorted_stats[:count]):
        if i == 0:
            server.say('§e🥇 §b{} §f- §a{} 方块'.format(player, total))
        elif i == 1:
            server.say('§e🥈 §b{} §f- §a{} 方块'.format(player, total))
        elif i == 2:
            server.say('§e🥉 §b{} §f- §a{} 方块'.format(player, total))
        else:
            server.say('§e{}. §b{} §f- §a{} 方块'.format(i + 1, player, total))

def show_placement_stats(server: PluginServerInterface, source: CommandSource):
    """显示放置榜"""
    count = config.get('top_count', 10)
    
    if not placement_stats:
        server.say('§c还没有放置数据，请先放置一些方块')
        return
    
    sorted_stats = sorted(placement_stats.items(), key=lambda x: x[1], reverse=True)
    
    # 使用server.say向所有玩家广播消息
    server.say('§6§l===== 放置榜 - 前{}名 ====='.format(min(count, len(sorted_stats))))
    for i, (player, total) in enumerate(sorted_stats[:count]):
        if i == 0:
            server.say('§e🥇 §b{} §f- §a{} 方块'.format(player, total))
        elif i == 1:
            server.say('§e🥈 §b{} §f- §a{} 方块'.format(player, total))
        elif i == 2:
            server.say('§e🥉 §b{} §f- §a{} 方块'.format(player, total))
        else:
            server.say('§e{}. §b{} §f- §a{} 方块'.format(i + 1, player, total))

def show_help(source: CommandSource):
    prefix = config['command_prefix']
    # 使用server全局广播或仍保持个人回复
    source.reply('§6§l===== 挖掘放置榜 - 帮助 =====')
    source.reply(f'§7{prefix} mine§f - 显示挖掘榜')
    source.reply(f'§7{prefix} place§f - 显示放置榜')
    source.reply(f'§7{prefix} update§f - 手动更新统计数据')
    source.reply(f'§7{prefix} debug§f - 显示调试信息')
    source.reply(f'§7{prefix} help§f - 显示此帮助信息')

def on_unload(server: PluginServerInterface):
    """插件卸载时清理资源"""
    global update_thread
    
    # 保存数据
    save_stats(server)
    
    # 清理计分板
    try:
        server.execute('scoreboard objectives remove stats_sidebar')
        server.execute('scoreboard objectives setdisplay sidebar')
        server.logger.info('已清理计分板')
    except Exception as e:
        server.logger.error(f'清理计分板时出错: {e}')
    
    # 强制结束线程
    update_thread = None
    
    server.logger.info('插件已完全卸载并清理资源') 