def read_job_info(dir, filename):
    path = dir / filename
    job_list = []
    job_attr_map = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if ',' in line:
            job, attr = line.strip().split(',', 1)
            job = job.strip()
            attr = int(attr.strip())
            job_list.append(job)
            job_attr_map[job] = attr
    return job_list, job_attr_map

# 从 dungeon.txt 中读取副本列表及等级、类型，保存为一个嵌套list
def read_dungeon_info(dir, filename):
    path = dir / filename
    dungeons = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if ',' in line:
            parts = line.strip().split(',')
            if len(parts) >= 3:
                dungeon_name = parts[0].strip()
                level = parts[1].strip()
                dungeon_type = parts[2].strip()
                dungeons.append([dungeon_name, level, dungeon_type])
    return dungeons

# 从 server.txt 读取副本
def read_server_info(dir, filename):
    path = dir / filename
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]