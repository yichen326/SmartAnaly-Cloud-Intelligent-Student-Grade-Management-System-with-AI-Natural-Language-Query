#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速测试脚本 - 测试系统核心功能"""

import os

# 删除旧数据库
if os.path.exists("school_final.db"):
    os.remove("school_final.db")

from main import GradeManagementSystem, StudentIDValidator, GradeEvaluator

gms = GradeManagementSystem()

# 1. 测试学号校验
print("=" * 60)
print("1. 学号校验测试")
print("=" * 60)

# 有效学号
tests = [
    ("202401001", True),
    ("202412345", True),
    ("202599999", True),
    ("1234567", False),    # 太短
    ("1234567890", False), # 太长
    ("2024a0001", False),  # 含字母
    ("202400001", False),  # 班级00
    ("202401", False),     # 太短
]

for sid, should_pass in tests:
    valid, result = StudentIDValidator.parse(sid)
    status = "通过" if valid else "拒绝"
    expected = "正确" if valid == should_pass else "!! 不符合预期 !!"
    info = result if not valid else result["display"]
    print(f"  学号 {sid}: {status} - {info} {expected}")

# 2. 添加9个测试学生
print("\n" + "=" * 60)
print("2. 添加测试学生 (9人)")
print("=" * 60)

students = [
    ("202401001", "张三", "男", 92, 88, 85, 90, 87, 91),
    ("202401002", "李四", "女", 78, 85, 90, 72, 68, 80),
    ("202401003", "王五", "男", 65, 70, 72, 68, 75, 70),
    ("202401004", "赵六", "女", 88, 92, 86, 90, 85, 89),
    ("202401005", "孙七", "男", 55, 60, 58, 62, 50, 65),
    ("202402001", "周八", "女", 95, 90, 92, 88, 93, 90),
    ("202402002", "吴九", "男", 72, 68, 75, 70, 65, 72),
    ("202402003", "郑十", "女", 82, 85, 80, 78, 82, 84),
    ("202402004", "陈十一", "男", 60, 55, 58, 62, 50, 58),
]

for sid, name, gender, *scores in students:
    success, msg = gms.add_student(sid, name, gender, *scores)
    status = "OK" if success else "FAIL"
    print(f"  [{status}] {msg if success else msg}")

# 3. 测试学号校验 - 错误场景
print("\n" + "=" * 60)
print("3. 学号错误校验测试")
print("=" * 60)

invalid_tests = [
    ("202401001", "张三", "男", 92, 88, 85, 90, 87, 91),  # 重复学号
    ("202401006", "", "男", 70, 70, 70, 70, 70, 70),  # 空姓名
    ("202401006", "测试", "其他", 70, 70, 70, 70, 70, 70),  # 无效性别
    ("202401006", "测试", "男", -1, 70, 70, 70, 70, 70),  # 负数成绩
    ("202401006", "测试", "男", 70, 70, 70, 70, 70, 101),  # 成绩>100
    ("20a401006", "测试", "男", 70, 70, 70, 70, 70, 70),  # 含字母学号
]

for sid, name, gender, *scores in invalid_tests:
    success, msg = gms.add_student(sid, name, gender, *scores)
    status = "拒绝正确" if not success else "!! 未拒绝 !!"
    print(f"  [{status}] {msg}")

# 4. 查询学生
print("\n" + "=" * 60)
print("4. 查询功能测试")
print("=" * 60)

for query in ["202401001", "张三", "不存在的人", "999999999"]:
    student = gms.query_student(query)
    if student:
        print(f"  查找「{query}」=> 找到 {student['name']} ({student['student_id']})")
    else:
        print(f"  查找「{query}」=> 未找到")

# 5. 班级排名
print("\n" + "=" * 60)
print("5. 班级排名测试 (2024级01班)")
print("=" * 60)

rankings = gms.query_class_ranking("2024", "01")
for i, s in enumerate(rankings, 1):
    print(f"  #{i}: {s['name']} 总分:{s['total_score']} 班级排名:{s['class_rank']} 年级排名:{s['grade_rank']}")

# 6. 年级排名
print("\n" + "=" * 60)
print("6. 年级排名测试 (2024级)")
print("=" * 60)

grade_ranks = gms.query_grade_ranking("2024")
for i, s in enumerate(grade_ranks, 1):
    print(f"  #{i}: {s['name']} ({s['class_name']}班) 总分:{s['total_score']} 班级排名:{s['class_rank']} 年级排名:{s['grade_rank']}")

# 7. 班级评估
print("\n" + "=" * 60)
print("7. 班级评估测试 (2024级01班)")
print("=" * 60)

eval_result = GradeEvaluator.evaluate_class(gms.db, "2024", "01")
if eval_result:
    print(f"  班级: {eval_result['grade']}")
    print(f"  人数: {eval_result['student_count']}")
    print(f"  均分: {eval_result['class_avg']}")
    print(f"  各科均分: {eval_result['subject_averages']}")
    print(f"  等级分布: {eval_result['level_distribution']}")
    print(f"  最高: {eval_result['max_student']} ({eval_result['max_score']}分)")
    print(f"  最低: {eval_result['min_student']} ({eval_result['min_score']}分)")

# 8. 年级评估
print("\n" + "=" * 60)
print("8. 年级评估测试 (2024级)")
print("=" * 60)

grade_result = GradeEvaluator.evaluate_grade(gms.db, "2024")
if grade_result:
    print(f"  年级: {grade_result['grade_year']}")
    print(f"  总人数: {grade_result['total_students']}")
    print(f"  班级数: {grade_result['class_count']}")
    print(f"  年级均分: {grade_result['grade_avg']}")

# 9. AI引擎测试
print("\n" + "=" * 60)
print("9. AI引擎模糊匹配测试")
print("=" * 60)

test_queries = [
    "你好",
    "帮助",
    "分析2024级01班的成绩",
    "查询张三",
    "我们班成绩怎么样",
    "班级排名",
    "谢谢",
    "整体情况如何",
    "菜单",
    "所有学生",
    "评估李四",
    "2024级年级排名",
    "今天天气真好",
    "加油学习",
]

for query in test_queries:
    response, func, params = gms.ai.process_query(query)
    func_name = func if func else "AI回复"
    print(f"\n  问: {query}")
    print(f"  匹配: [{func_name}]")
    print(f"  答: {response[:100]}...")

# 10. 统计
print("\n" + "=" * 60)
print("10. 系统统计")
print("=" * 60)

stats = gms.get_statistics()
print(f"  学生总数: {stats['total_students']}")
print(f"  班级总数: {stats['total_classes']}")
print(f"  年级均分: {stats['avg_total']}")
if stats['top_student']:
    print(f"  第一名: {stats['top_student']['name']} ({stats['top_student']['total_score']}分)")
print(f"  及格率: {stats['pass_rate']}%")

# 11. 修改成绩与删除
print("\n" + "=" * 60)
print("11. 修改成绩 & 删除测试")
print("=" * 60)

success, msg = gms.update_grade("202401001", 95, 90, 88, 92, 89, 93)
print(f"  修改成绩: {'OK' if success else 'FAIL'} - {msg}")

# 验证修改
student = gms.query_student("202401001")
if student:
    print(f"  验证: {student['name']} 新总分={student['total_score']}, 班级排名={student['class_rank']}")

# 12. 格式化输出
print("\n" + "=" * 60)
print("12. 格式化输出测试")
print("=" * 60)

student = gms.query_student("202402001")
if student:
    print(gms.format_student_info(student, detailed=True))
    print()

print(gms.format_class_ranking(rankings, "2024", "01"))
print()
print(gms.format_grade_ranking(grade_ranks, "2024"))
print()
print(gms.format_statistics(stats))
print()
print(gms.format_evaluation(eval_result))
print()

# 学生个人评估
student = gms.query_student("202402001")
if student:
    eval_stu = GradeEvaluator.evaluate_student(student)
    print(gms.format_student_evaluation(eval_stu))

gms.close()
print("\n" + "=" * 60)
print("所有测试完成!")
print("=" * 60)
