import json
import os
import time
import re
import uuid as uuid_lib
import threading
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

# 配置文件与数据存储路径
CONFIG_FILE = 'config/mining_placement_stats.json'
STATS_FILE = 'config/mining_placement_stats_data.json'

# 默认配置参数
DEFAULT_CONFIG = {
    'command_prefix': '!!pls',  # 命令前缀
    'top_count': 10,            # 排行榜显示数量
    'update_interval': 300,     # 数据自动更新间隔(秒)
    'debug': True               # 调试模式开关
}

# 全局数据结构
mining_stats = {}               # 挖掘统计数据 {玩家名: 总数量}
placement_stats = {}            # 放置统计数据 {玩家名: 总数量}
config = DEFAULT_CONFIG.copy()  # 当前配置
update_thread = None            # 更新线程引用
SCOREBOARD_NAME = 'stats_sidebar'  # 计分板名称
whitelist_players = set()       # 白名单玩家集合

def load_config(server: PluginServerInterface):
    """
    加载插件配置文件
    如果配置文件不存在则创建默认配置
    """
    global config
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        save_config(server)
    server.logger.info(f'已加载配置: {config}')

def save_config(server: PluginServerInterface):
    """
    保存插件配置到文件
    确保配置目录存在
    """
    if not os.path.exists('config'):
        os.makedirs('config')
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def load_stats(server: PluginServerInterface):
    """
    加载玩家统计数据
    如果数据文件不存在则创建空数据
    """
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
    """
    保存统计数据到文件
    确保配置目录存在
    """
    if not os.path.exists('config'):
        os.makedirs('config')
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'mining': mining_stats,
            'placement': placement_stats
        }, f, indent=4, ensure_ascii=False)

def load_whitelist(server: PluginServerInterface):
    """
    从服务器加载白名单玩家列表
    白名单用于过滤排行榜中显示的玩家
    """
    global whitelist_players
    whitelist_players = set()
    
    # 获取当前工作目录
    current_dir = os.path.abspath('.')
    
    # 使用标准位置
    whitelist_path = os.path.join(current_dir, 'server', 'whitelist.json')
    
    server.logger.info(f'使用白名单路径: {whitelist_path}')
    
    if os.path.exists(whitelist_path):
        try:
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = json.load(f)
                for entry in whitelist:
                    name = entry.get('name')
                    if name:
                        whitelist_players.add(name)
            server.logger.info(f'成功加载白名单玩家: {len(whitelist_players)}人')
            server.logger.info(f'白名单玩家列表: {", ".join(whitelist_players)}')
        except Exception as e:
            server.logger.error(f'读取白名单文件出错: {e}')
    else:
        server.logger.warning(f'白名单文件不存在: {whitelist_path}')

def on_load(server: PluginServerInterface, prev):
    """
    插件加载入口函数
    初始化配置、数据并注册命令
    """
    global update_thread
    load_config(server)
    load_stats(server)
    load_whitelist(server)
    register_commands(server)
    server.register_help_message(config['command_prefix'], '查看挖掘榜和放置榜')
    
    # 启动定时更新任务
    schedule_update_task(server)

def schedule_update_task(server: PluginServerInterface):
    """
    安排定时更新任务
    创建后台线程定期更新统计数据
    """
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
    """
    注册插件命令树
    包括查看挖掘榜、放置榜、手动更新和帮助命令
    """
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
    """
    显示调试信息
    包括配置、数据状态和服务器环境信息
    """
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
    """
    手动更新统计数据命令处理函数
    更新所有玩家数据并重新加载白名单
    """
    server.say('§a正在更新所有玩家的挖掘和放置统计数据...')
    updated_count = update_stats_for_all_players(server)
    load_whitelist(server)
    server.say(f'§a数据更新完成！共更新了{updated_count}名玩家的数据')

def update_stats_for_all_players(server: PluginServerInterface) -> int:
    """
    更新所有玩家的统计数据
    从统计文件中读取并解析挖掘和放置数据
    
    返回值:
        int: 成功更新的玩家数量
    """
    server_dir = os.path.abspath('.')
    updated_count = 0
    processed_count = 0
    
    # 保存更新前的数据用于比较
    old_mining_stats = dict(mining_stats)  # 使用dict()创建深拷贝
    old_placement_stats = dict(placement_stats)
    
    # 清空当前统计数据
    mining_stats.clear()
    placement_stats.clear()
    
    stats_dirs = [
        os.path.join(server_dir, 'server', 'world', 'stats'),
    ]
    
    for stats_dir in stats_dirs:
        if not os.path.exists(stats_dir):
            server.logger.info(f'统计目录不存在: {stats_dir}')
            continue
        
        server.logger.info(f'我的统计目录: {stats_dir}')
        
        stats_files = os.listdir(stats_dir)
        server.logger.info(f'找到统计文件: {len(stats_files)}个')
        
        for filename in stats_files:
            if not filename.endswith('.json'):
                continue
            
            processed_count += 1
            # 从文件名获取UUID
            uuid = filename.split('.')[0]
            
            try:
                # 读取统计数据
                file_path = os.path.join(stats_dir, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
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
                
                # 获取玩家名
                player_name = get_player_name(server, uuid)
                if not player_name:
                    # 如果无法获取玩家名，使用UUID前缀
                    player_name = f"Player_{uuid[:8]}"
                
                # 记录数据变化情况
                old_mine = old_mining_stats.get(player_name, -1)  # -1表示新玩家
                old_place = old_placement_stats.get(player_name, -1)
                
                # 存储新数据
                mining_stats[player_name] = mine_count
                placement_stats[player_name] = place_count
                
                # 比较数据变化
                if old_mine != mine_count or old_place != place_count:
                    server.logger.info(f'玩家 {player_name} 数据已更新: 挖掘 {old_mine} -> {mine_count}, 放置 {old_place} -> {place_count}')
                    updated_count += 1
                
            except Exception as e:
                server.logger.error(f'处理玩家{uuid}的统计数据时出错: {e}')
                server.logger.error(f'错误详情: {str(e)}')
        
        # 如果已经处理了统计文件，就不再继续查找
        if processed_count > 0:
            break
    
    # 数据统计信息
    server.logger.info(f'数据汇总: 旧数据 {len(old_mining_stats)}条, 新数据 {len(mining_stats)}条')
    
    # 检查白名单玩家是否存在于统计数据中
    found_in_mining = []
    found_in_placement = []
    
    for player in whitelist_players:
        player_lower = player.lower()
        
        # 检查挖掘数据
        for stat_player in mining_stats.keys():
            if stat_player.lower() == player_lower:
                found_in_mining.append(player)
                break
                
        # 检查放置数据
        for stat_player in placement_stats.keys():
            if stat_player.lower() == player_lower:
                found_in_placement.append(player)
                break
    
    server.logger.info(f'白名单玩家在挖掘数据中找到: {len(found_in_mining)}/{len(whitelist_players)}')
    server.logger.info(f'白名单玩家在放置数据中找到: {len(found_in_placement)}/{len(whitelist_players)}')
    
    # 保存更新后的统计数据
    save_stats(server)
    server.logger.info(f'统计更新: 处理了{processed_count}个文件, 数据有变化的玩家{updated_count}名')
    return updated_count

def get_player_name(server: PluginServerInterface, uuid: str) -> Optional[str]:
    """
    尝试从UUID获取玩家名称
    优先匹配白名单玩家名称
    
    参数:
        server: 服务器接口
        uuid: 玩家UUID
        
    返回:
        玩家名称或None
    """
    try:
        # 规范化UUID格式
        clean_uuid = uuid.replace('-', '').lower()
        
        # 尝试从UUID缓存文件读取
        usercache_paths = [
            os.path.join(os.path.abspath('.'), 'usercache.json'),
            os.path.join(os.path.abspath('.'), 'server', 'usercache.json')
        ]
        
        for usercache_path in usercache_paths:
            if os.path.exists(usercache_path):
                with open(usercache_path, 'r', encoding='utf-8') as f:
                    usercache = json.load(f)
                    for entry in usercache:
                        entry_uuid = entry.get('uuid', '').replace('-', '').lower()
                        if entry_uuid == clean_uuid:
                            # 检查玩家是否在白名单中
                            name = entry.get('name')
                            if name:
                                # 尝试精确匹配
                                if name in whitelist_players:
                                    return name
                                
                                # 尝试不区分大小写匹配
                                name_lower = name.lower()
                                for whitelist_name in whitelist_players:
                                    if whitelist_name.lower() == name_lower:
                                        server.logger.info(f'UUID {uuid} 玩家名称匹配: {name} -> {whitelist_name}')
                                        return whitelist_name  # 返回白名单中的精确名称
                                
                                return name  # 返回原始名称
        
        # 如果都失败了，直接使用UUID的一部分作为临时名称
        return f"Player_{uuid[:8]}"
    except Exception as e:
        server.logger.error(f'获取玩家{uuid}的名称时出错: {e}')
        return f"Player_{uuid[:8]}"  # 确保有返回值

def show_mining_stats(server: PluginServerInterface, source: CommandSource):
    """
    显示挖掘榜
    仅显示白名单内玩家的数据，按挖掘数量降序排列
    """
    # 记录调试信息
    server.logger.info(f'白名单玩家: {len(whitelist_players)}人, 挖掘数据: {len(mining_stats)}条')
    server.logger.info(f'白名单玩家: {", ".join(whitelist_players)}')
    server.logger.info(f'统计玩家: {", ".join(mining_stats.keys())}')
    
    # 过滤数据，使用更宽松的匹配规则
    filtered_stats = {}
    for player_name, count in mining_stats.items():
        # 尝试精确匹配
        if player_name in whitelist_players:
            filtered_stats[player_name] = count
            continue
            
        # 尝试不区分大小写匹配
        player_lower = player_name.lower()
        for whitelist_name in whitelist_players:
            if whitelist_name.lower() == player_lower:
                filtered_stats[whitelist_name] = count  # 使用白名单中的名称
                server.logger.info(f'挖掘数据: 通过不区分大小写匹配到玩家 {player_name} -> {whitelist_name}')
                break
    
    if not filtered_stats:
        source.reply('§c没有白名单玩家的挖掘数据')
        return
    
    sorted_data = sorted(filtered_stats.items(), key=lambda x: x[1], reverse=True)
    source.reply(f'§6§l===== 挖掘榜 - 前{min(config["top_count"], len(sorted_data))}名 =====')
    
    for i, (name, count) in enumerate(sorted_data[:config['top_count']]):
        rank_color = '§e' if i < 3 else '§f'  # 前三名用金色
        source.reply(f'{rank_color}{i+1}. {name} - {count} 方块')

def show_placement_stats(server: PluginServerInterface, source: CommandSource):
    """
    显示放置榜
    仅显示白名单内玩家的数据，按放置数量降序排列
    """
    # 记录调试信息
    server.logger.info(f'白名单玩家: {len(whitelist_players)}人, 放置数据: {len(placement_stats)}条')
    
    # 过滤数据，使用更宽松的匹配规则
    filtered_stats = {}
    for player_name, count in placement_stats.items():
        # 尝试精确匹配
        if player_name in whitelist_players:
            filtered_stats[player_name] = count
            continue
            
        # 尝试不区分大小写匹配
        player_lower = player_name.lower()
        for whitelist_name in whitelist_players:
            if whitelist_name.lower() == player_lower:
                filtered_stats[whitelist_name] = count  # 使用白名单中的名称
                server.logger.info(f'放置数据: 通过不区分大小写匹配到玩家 {player_name} -> {whitelist_name}')
                break
    
    if not filtered_stats:
        source.reply('§c没有白名单玩家的放置数据')
        return
    
    sorted_data = sorted(filtered_stats.items(), key=lambda x: x[1], reverse=True)
    source.reply(f'§6§l===== 放置榜 - 前{min(config["top_count"], len(sorted_data))}名 =====')
    
    for i, (name, count) in enumerate(sorted_data[:config['top_count']]):
        rank_color = '§e' if i < 3 else '§f'  # 前三名用金色
        source.reply(f'{rank_color}{i+1}. {name} - {count} 方块')

def show_help(source: CommandSource):
    """
    显示帮助信息
    列出所有可用命令及其功能描述
    """
    prefix = config['command_prefix']
    source.reply('§6§l===== 挖掘放置榜 - 帮助 =====')
    source.reply(f'§7{prefix} mine§f - 显示挖掘榜')
    source.reply(f'§7{prefix} place§f - 显示放置榜')
    source.reply(f'§7{prefix} update§f - 手动更新统计数据')
    source.reply(f'§7{prefix} debug§f - 显示调试信息')
    source.reply(f'§7{prefix} help§f - 显示此帮助信息')

def on_unload(server: PluginServerInterface):
    """
    插件卸载函数
    清理资源并保存数据
    """
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
    
    # 结束线程
    update_thread = None
    
    server.logger.info('插件已完全卸载并清理资源') 