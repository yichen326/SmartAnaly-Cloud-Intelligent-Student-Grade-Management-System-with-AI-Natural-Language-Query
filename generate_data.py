#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成100条标准学生数据，导出到 students_data.txt
格式: 学号|姓名|性别|语文|数学|英语|物理|化学|生物
"""

import random
import os

random.seed(42)

GRADE_NAMES = {"01": "高一", "02": "高二", "03": "高三"}
NAMES_MALE = ["赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", 
              "褚", "卫", "蒋", "沈", "韩", "杨", "朱", "秦", "尤", "许",
              "何", "吕", "施", "张", "孔", "曹", "严", "华", "金", "魏",
              "陶", "姜", "戚", "谢", "邹", "喻", "柏", "水", "窦", "章",
              "云", "苏", "潘", "葛", "奚", "范", "彭", "郎", "鲁", "韦"]
NAMES_FEMALE = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
                "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
                "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧"]
NAMES_SUFFIX = ["明", "华", "强", "伟", "刚", "峰", "勇", "军", "杰", "磊",
                "涛", "辉", "鹏", "飞", "超", "波", "斌", "俊", "浩", "宇",
                "静", "婷", "芳", "娜", "娟", "敏", "洁", "琳", "雪", "霞",
                "燕", "萍", "红", "玲", "芬", "英", "丽", "艳", "颖", "慧"]

def generate_score(level='middle'):
    """生成符合正态分布的成绩"""
    if level == 'high':
        return min(100, max(60, int(random.gauss(88, 8))))
    elif level == 'low':
        return min(100, max(30, int(random.gauss(55, 12))))
    else:
        return min(100, max(40, int(random.gauss(75, 14))))

def generate_name(gender):
    if gender == '男':
        return random.choice(NAMES_MALE) + random.choice(NAMES_SUFFIX)
    else:
        return random.choice(NAMES_FEMALE) + random.choice(NAMES_SUFFIX[:20])

def generate_students(count=100):
    students = []
    serials = {"01": {}, "02": {}, "03": {}}
    
    # 确定各年级人数
    grade_counts = {"01": count // 3 + (1 if count % 3 >= 1 else 0),
                    "02": count // 3 + (1 if count % 3 >= 2 else 0),
                    "03": count // 3}
    
    for grade_code, gcount in grade_counts.items():
        # 确定班级分布
        num_classes = random.randint(2, 4)
        classes = [f"{i+1:02d}" for i in range(num_classes)]
        
        students_per_class = gcount // num_classes
        extra = gcount % num_classes
        
        for i, class_code in enumerate(classes):
            class_size = students_per_class + (1 if i < extra else 0)
            for j in range(1, class_size + 1):
                serial_num = f"{j:04d}"
                student_id = grade_code + class_code + serial_num
                
                gender = random.choice(['男', '女'])
                name = generate_name(gender)
                
                if gender == '女':
                    scores = [generate_score('high') for _ in range(6)]
                elif random.random() < 0.2:
                    scores = [generate_score('low') for _ in range(6)]
                else:
                    scores = [generate_score() for _ in range(6)]
                
                students.append((student_id, name, gender, scores))
    
    # 按学号排序
    students.sort(key=lambda x: x[0])
    return students[:count]

def main():
    students = generate_students(100)
    
    with open('students_data.txt', 'w', encoding='utf-8') as f:
        f.write("# 智析云途 学生成绩数据\n")
        f.write("# 格式: 学号|姓名|性别|语文|数学|英语|物理|化学|生物\n")
        f.write(f"# 共 {len(students)} 条记录\n")
        f.write("# 学号标准: 8位 GGCCNNNN (2位年级+2位班级+4位顺序号)\n")
        f.write("# 年级: 01=高一, 02=高二, 03=高三\n\n")
        
        for sid, name, gender, scores in students:
            score_str = "|".join(str(s) for s in scores)
            f.write(f"{sid}|{name}|{gender}|{score_str}\n")
    
    print(f"✅ 已生成 {len(students)} 条学生数据到 students_data.txt")
    
    # 统计
    grades = {"01": "高一", "02": "高二", "03": "高三"}
    grade_stats = {}
    for g in ["01", "02", "03"]:
        gs = [s for s in students if s[0][:2] == g]
        classes = set(s[0][2:4] for s in gs)
        grade_stats[g] = (len(gs), len(classes))
    
    for g, (n, c) in grade_stats.items():
        print(f"  {grades[g]}: {n}人, {c}个班级")
    
    print(f"  男生: {sum(1 for s in students if s[2]=='男')}人")
    print(f"  女生: {sum(1 for s in students if s[2]=='女')}人")

if __name__ == "__main__":
    main()
