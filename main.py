#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智析云途 - AI智能学生成绩管理系统 (完全重写版 v2.1)
======================================================
基于 PyQt5 + DeepSeek API + SQLite3
学号标准: 8位 GGCCNNNN (2位年级+2位班级+4位顺序号)
  年级: 01=高一, 02=高二, 03=高三
  班级: 01-30
  顺序号: 0001-9999
"""

import sys
import os
import re
import json
import random
import sqlite3
import threading
import time
import traceback
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any

# ===================== GBK安全打印 =====================
_ORIGINAL_PRINT = print
def safe_print(*args, **kwargs):
    """GBK安全的打印函数，替换可能导致编码错误的emoji等字符"""
    try:
        encoding = sys.stdout.encoding or 'gbk'
        args_encoded = []
        for arg in args:
            if isinstance(arg, str):
                try:
                    arg.encode(encoding)
                    args_encoded.append(arg)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    args_encoded.append(arg.encode(encoding, errors='replace').decode(encoding))
            else:
                args_encoded.append(arg)
        _ORIGINAL_PRINT(*args_encoded, **kwargs)
    except Exception:
        pass  # 彻底静默失败
print = safe_print

# ===================== PyQt5 导入 =====================
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLineEdit, QLabel, QDialog, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QComboBox,
    QSplitter, QFrame, QGridLayout, QGroupBox,
    QDialogButtonBox, QFileDialog, QTabWidget, QSizePolicy,
    QAbstractItemView, QStatusBar, QMenu, QAction, QInputDialog
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QSize, QTimer, QUrl, QPoint
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QIcon, QPixmap,
    QBrush, QTextCharFormat, QDoubleValidator, QIntValidator,
    QCursor
)

# ===================== API 导入 =====================
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ===================== 配置区 =====================

def _load_config() -> dict:
    """从 config.json 加载配置，若不存在则使用默认值"""
    import os as _os
    _defaults = {
        "deepseek": {
            "api_key": "",
            "api_url": "https://api.deepseek.com/v1/chat/completions",
            "model": "deepseek-chat"
        },
        "files": {
            "data_file": "students_data.txt",
            "db_file": "school_final.db"
        },
        "login": {
            "username": "admin",
            "password": "123456"
        }
    }
    _config_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "config.json")
    if _os.path.exists(_config_path):
        try:
            import json as _json
            with open(_config_path, 'r', encoding='utf-8') as _f:
                _user_cfg = _json.load(_f)
            # 深度合并
            def _deep_merge(base, override):
                for k, v in override.items():
                    if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                        _deep_merge(base[k], v)
                    else:
                        base[k] = v
            _deep_merge(_defaults, _user_cfg)
        except Exception as _e:
            print(f"[配置] 加载 config.json 失败: {_e}，使用默认值")
    # 兼容环境变量覆盖（用于敏感信息）
    import os as _os2
    _env_key = _os2.environ.get("DEEPSEEK_API_KEY", "")
    if _env_key:
        _defaults["deepseek"]["api_key"] = _env_key
    return _defaults

_CONFIG = _load_config()

DEEPSEEK_API_KEY = _CONFIG["deepseek"]["api_key"]
DEEPSEEK_API_URL = _CONFIG["deepseek"]["api_url"]
DEEPSEEK_MODEL = _CONFIG["deepseek"]["model"]

GRADE_NAMES = {"01": "高一", "02": "高二", "03": "高三"}
GRADE_CODES = {"高一": "01", "高二": "02", "高三": "03"}

# 成绩等级：纯中文，无特殊符号
GRADE_LEVELS = [
    (90, 100, "优秀"),
    (80, 89,  "良好"),
    (70, 79,  "中等"),
    (60, 69,  "及格"),
    (0, 59,   "不及格")
]

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]
SUBJECT_FIELDS = ["chinese", "math", "english", "physics", "chemistry", "biology"]

# 数据文件路径：优先使用可执行文件所在目录下的文件
if getattr(sys, 'frozen', False):
    # 打包后，数据文件在可执行文件所在目录
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(_BASE_DIR, _CONFIG["files"]["data_file"])
DB_FILE = os.path.join(_BASE_DIR, _CONFIG["files"]["db_file"])
CONFIG_FILE = os.path.join(_BASE_DIR, "config.json")

# 登录凭据
_LOGIN_USERNAME = _CONFIG["login"]["username"]
_LOGIN_PASSWORD = _CONFIG["login"]["password"]

# ===================== 学号校验 =====================

class StudentIDValidator:
    """学号校验器 - 8位格式 GGCCNNNN"""

    STUDENT_ID_PATTERN = r"^(01|02|03)(0[1-9]|[12]\d|30)\d{4}$"

    @staticmethod
    def parse(student_id: str) -> Tuple[bool, Any]:
        """校验并解析学号"""
        student_id = student_id.strip()

        if not student_id.isdigit():
            return False, "学号必须为纯数字！"
        if len(student_id) != 8:
            return False, f"学号长度应为8位，当前为{len(student_id)}位！\n格式: 2位年级+2位班级+4位序号"
        if not re.match(StudentIDValidator.STUDENT_ID_PATTERN, student_id):
            return False, (f"学号格式不正确！\n年级: 01=高一, 02=高二, 03=高三\n班级: 01-30\n序号: 0001-9999\n示例: 01010001")

        grade_code = student_id[:2]
        class_code = student_id[2:4]
        serial = student_id[4:]
        grade_name = GRADE_NAMES.get(grade_code, f"{grade_code}年级")

        return True, {
            "student_id": student_id,
            "grade_code": grade_code,
            "class_code": class_code,
            "grade_name": grade_name,
            "display": f"{grade_name}{class_code}班{serial}号"
        }

# ===================== 数据库模块 =====================

class Database:
    """数据库管理类"""

    def __init__(self, db_name=DB_FILE):
        self.db_name = db_name
        self.conn = None
        self.c = None
        self._connect()
        self._create_tables()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.c = self.conn.cursor()

    def _create_tables(self):
        """创建标准表结构"""
        self.c.executescript('''
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                gender TEXT CHECK(gender IN ('男','女')),
                grade_code TEXT NOT NULL DEFAULT '01',
                class_code TEXT NOT NULL DEFAULT '01',
                chinese REAL DEFAULT 0,
                math REAL DEFAULT 0,
                english REAL DEFAULT 0,
                physics REAL DEFAULT 0,
                chemistry REAL DEFAULT 0,
                biology REAL DEFAULT 0,
                total_score REAL DEFAULT 0,
                class_rank INTEGER DEFAULT -1,
                grade_rank INTEGER DEFAULT -1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        self.conn.commit()

    def load_from_txt(self, filepath=DATA_FILE):
        """从txt文件加载数据, 返回(成功数, 跳过数, 错误详情列表)"""
        if not os.path.exists(filepath):
            return 0, 0, []

        count = 0
        skipped = 0
        errors = []
        line_no = 0

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line_no += 1
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split('|')
                if len(parts) < 9:
                    skipped += 1
                    errors.append(f"第{line_no}行: 字段不足({len(parts)}个), 需要至少9个字段")
                    continue

                student_id = parts[0].strip()
                name = parts[1].strip()
                gender = parts[2].strip()

                if gender not in ('男', '女'):
                    errors.append(f"第{line_no}行({name or '匿名'}): 性别「{gender}」无效, 已设为'男'")
                    gender = '男'

                try:
                    scores = [float(p.strip()) for p in parts[3:9]]
                except ValueError as e:
                    skipped += 1
                    errors.append(f"第{line_no}行({name or student_id}): 成绩格式错误 - {e}")
                    continue

                if len(scores) != 6:
                    skipped += 1
                    errors.append(f"第{line_no}行({name or student_id}): 成绩数量不是6科")
                    continue

                valid, info = StudentIDValidator.parse(student_id)
                if not valid:
                    skipped += 1
                    errors.append(f"第{line_no}行({name or student_id}): 学号「{student_id}」校验失败 - {info}")
                    continue

                total = sum(scores)
                try:
                    self.execute("""
                        INSERT OR IGNORE INTO students 
                        (student_id, name, gender, grade_code, class_code,
                         chinese, math, english, physics, chemistry, biology, total_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (student_id, name, gender, info["grade_code"], info["class_code"],
                          scores[0], scores[1], scores[2], scores[3], scores[4], scores[5], total))
                    if self.c.rowcount > 0:
                        count += 1
                    else:
                        skipped += 1
                        errors.append(f"第{line_no}行({name}): 学号「{student_id}」已存在, 跳过")
                except Exception as e:
                    skipped += 1
                    errors.append(f"第{line_no}行({name or student_id}): 数据库插入错误 - {e}")

        if count > 0:
            self.update_all_ranks()

        return count, skipped, errors

    def execute(self, sql, params=()):
        self.c.execute(sql, params)
        self.conn.commit()

    def fetchall(self, sql, params=()):
        self.c.execute(sql, params)
        return self.c.fetchall()

    def fetchone(self, sql, params=()):
        self.c.execute(sql, params)
        return self.c.fetchone()

    def close(self):
        if self.conn:
            self.conn.close()

    def get_available_grades(self) -> List[str]:
        """获取数据库中有数据的年级代码列表"""
        rows = self.fetchall("SELECT DISTINCT grade_code FROM students ORDER BY grade_code")
        return [r["grade_code"] for r in rows]

    def get_available_classes(self, grade_code=None) -> List[str]:
        """获取数据库中指定年级（或全部）的班级代码列表"""
        if grade_code:
            rows = self.fetchall(
                "SELECT DISTINCT class_code FROM students WHERE grade_code=? ORDER BY class_code",
                (grade_code,)
            )
        else:
            rows = self.fetchall("SELECT DISTINCT class_code FROM students ORDER BY class_code")
        return [r["class_code"] for r in rows]

    def update_all_ranks(self):
        """更新所有排名 (try/except保护)"""
        try:
            # 班级排名
            class_groups = self.fetchall(
                "SELECT DISTINCT grade_code, class_code FROM students"
            )
            for group in class_groups:
                rows = self.fetchall(
                    "SELECT id FROM students WHERE grade_code=? AND class_code=? ORDER BY total_score DESC",
                    (group["grade_code"], group["class_code"])
                )
                for i, row in enumerate(rows, 1):
                    self.execute("UPDATE students SET class_rank=? WHERE id=?", (i, row["id"]))

            # 年级排名
            grade_groups = self.fetchall("SELECT DISTINCT grade_code FROM students")
            for group in grade_groups:
                rows = self.fetchall(
                    "SELECT id FROM students WHERE grade_code=? ORDER BY total_score DESC",
                    (group["grade_code"],)
                )
                for i, row in enumerate(rows, 1):
                    self.execute("UPDATE students SET grade_rank=? WHERE id=?", (i, row["id"]))
        except Exception as e:
            print(f"[排名更新] 出错: {e}")

# ===================== 成绩评估模块 =====================

class GradeEvaluator:
    """成绩评估与分析模块"""

    @staticmethod
    def get_grade_level(score: float) -> str:
        """获取成绩等级，只返回纯中文"""
        # 限制范围0-100并处理边界值（如89.5）
        score = max(0, min(100, score))
        for low, high, level in GRADE_LEVELS:
            if low <= score <= high:
                return level
        # 兜底边界处理
        if score >= 85:
            return "良好"
        elif score >= 75:
            return "中等"
        elif score >= 60:
            return "及格"
        else:
            return "不及格"

    @staticmethod
    def evaluate_student(student) -> Dict:
        """评估单个学生"""
        subjects_data = [
            ("语文", student["chinese"]),
            ("数学", student["math"]),
            ("英语", student["english"]),
            ("物理", student["physics"]),
            ("化学", student["chemistry"]),
            ("生物", student["biology"])
        ]

        total = student["total_score"]
        avg = total / 6
        level = GradeEvaluator.get_grade_level(avg)

        strong = []
        weak = []
        details = []
        for name, score in subjects_data:
            lv = GradeEvaluator.get_grade_level(score)
            details.append({"subject": name, "score": score, "level": lv})
            if lv == "优秀":
                strong.append(name)
            elif lv == "不及格":
                weak.append(name)

        comments = []
        if strong:
            comments.append(f"优势科目: {'、'.join(strong)}，继续保持！")
        if weak:
            comments.append(f"待加强科目: {'、'.join(weak)}，建议多花时间复习。")
        if level == "优秀":
            comments.append("总评优秀，非常出色！继续加油！")
        elif level == "良好":
            comments.append("总评良好，还有提升空间，继续努力！")
        elif level == "中等":
            comments.append("总评中等，制定学习计划争取进步！")
        elif level == "及格":
            comments.append("总评及格，需要更加努力！")
        else:
            comments.append("总评偏低，建议调整学习方法，寻求帮助！")

        return {
            "name": student["name"],
            "student_id": student["student_id"],
            "grade": f"{GRADE_NAMES.get(student['grade_code'], student['grade_code'])}{student['class_code']}班",
            "total": total,
            "average": round(avg, 1),
            "level": level,
            "class_rank": student["class_rank"],
            "grade_rank": student["grade_rank"],
            "strong_subjects": strong,
            "weak_subjects": weak,
            "details": details,
            "comments": " ".join(comments)
        }

    @staticmethod
    def evaluate_class(db: Database, grade_code: str, class_code: str) -> Optional[Dict]:
        """评估班级"""
        students = db.fetchall(
            "SELECT * FROM students WHERE grade_code=? AND class_code=? ORDER BY total_score DESC",
            (grade_code, class_code)
        )
        if not students:
            return None

        count = len(students)
        total_sum = sum(s["total_score"] for s in students)
        class_avg = round(total_sum / count, 1)

        subject_avgs = {}
        for sname, sfield in zip(SUBJECTS, SUBJECT_FIELDS):
            avg_val = round(sum(s[sfield] for s in students) / count, 1)
            subject_avgs[sname] = avg_val

        level_dist = {"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0}
        for s in students:
            avg_score = s["total_score"] / 6
            lv = GradeEvaluator.get_grade_level(avg_score)
            level_dist[lv] = level_dist.get(lv, 0) + 1

        max_total = max(s["total_score"] for s in students)
        min_total = min(s["total_score"] for s in students)
        max_s = [s for s in students if s["total_score"] == max_total][0]
        min_s = [s for s in students if s["total_score"] == min_total][0]

        grade_name = GRADE_NAMES.get(grade_code, f"{grade_code}年级")

        return {
            "grade": f"{grade_name}{class_code}班",
            "grade_code": grade_code,
            "class_code": class_code,
            "student_count": count,
            "class_avg": class_avg,
            "subject_averages": subject_avgs,
            "level_distribution": level_dist,
            "max_score": max_total,
            "max_student": max_s["name"],
            "min_score": min_total,
            "min_student": min_s["name"],
            "pass_count": sum(1 for s in students if s["total_score"] >= 360),
            "excellent_count": sum(1 for s in students if s["total_score"] / 6 >= 90),
        }

    @staticmethod
    def evaluate_grade(db: Database, grade_code: str) -> Optional[Dict]:
        """评估年级"""
        classes = db.fetchall(
            "SELECT DISTINCT class_code FROM students WHERE grade_code=? ORDER BY class_code",
            (grade_code,)
        )

        results = []
        for cls in classes:
            result = GradeEvaluator.evaluate_class(db, grade_code, cls["class_code"])
            if result:
                results.append(result)

        if not results:
            return None

        total_students = sum(r["student_count"] for r in results)
        all_avgs = [r["class_avg"] for r in results]
        grade_avg = round(sum(all_avgs) / len(all_avgs), 1) if all_avgs else 0

        return {
            "grade_code": grade_code,
            "grade_name": GRADE_NAMES.get(grade_code, f"{grade_code}年级"),
            "total_students": total_students,
            "class_count": len(results),
            "grade_avg": grade_avg,
            "classes": results
        }

# ===================== DeepSeek AI 模块 =====================

class DeepSeekAI:
    """DeepSeek API 调用封装"""

    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key
        self.api_url = DEEPSEEK_API_URL
        self.model = DEEPSEEK_MODEL
        self.available = REQUESTS_AVAILABLE and bool(api_key)

    def chat(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 1000) -> Optional[str]:
        if not self.available:
            return None
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False
            }
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                print(f"[DeepSeek API] 错误: {response.status_code} {response.text[:200]}")
                return None
        except Exception as e:
            print(f"[DeepSeek API] 异常: {e}")
            return None

    def get_system_prompt(self, db_context: str) -> str:
        return f"""你是一个智能学生成绩管理系统的AI助手"智析云途"。

当前系统数据库包含以下数据：
{db_context}

本系统核心功能是【学生成绩数据库管理】，包括学籍管理、成绩录入、班级/年级排名、成绩分析评估等。

你的回答规则：
1. 【成绩/数据相关问题】- 基于系统数据给出专业、准确的分析，可适当展开（100-200字）
2. 【非数据/日常生活问题】- 用1-2句话简短友好回复（严格控制在20-50字内），然后必须补充一句说明本系统主要提供学生成绩数据库管理服务
3. 【语气风格】温暖、鼓励、专业
4. 【字数限制】日常问题回复总字数不超过50字，其中系统功能说明必须包含"""

    def build_context(self, db: Database) -> str:
        try:
            total = db.fetchone("SELECT COUNT(*) as cnt FROM students")
            count = total["cnt"] if total else 0
            if count == 0:
                return "（系统中暂无学生数据）"

            grade_classes = db.fetchall(
                "SELECT grade_code, class_code, COUNT(*) as cnt FROM students GROUP BY grade_code, class_code"
            )
            lines = [f"共有 {count} 名学生"]
            grade_summary = {}
            for gc in grade_classes:
                gn = GRADE_NAMES.get(gc["grade_code"], gc["grade_code"])
                key = f"{gn}({gc['grade_code']})"
                if key not in grade_summary:
                    grade_summary[key] = {"total": 0, "classes": set()}
                grade_summary[key]["total"] += gc["cnt"]
                grade_summary[key]["classes"].add(gc["class_code"])
            for gn, info in grade_summary.items():
                lines.append(f"- {gn}: {info['total']}人, {len(info['classes'])}个班级")

            stats = db.fetchone("SELECT AVG(total_score) as avg_s, MIN(total_score) as min_s, MAX(total_score) as max_s FROM students")
            if stats and stats["avg_s"]:
                lines.append(f"总分范围: {stats['min_s']:.0f} - {stats['max_s']:.0f}, 平均分: {stats['avg_s']:.1f}")
            return "\n".join(lines)
        except Exception as e:
            return f"（获取数据上下文时出错: {e}）"


# ===================== AI 智能问答引擎 =====================

class AIChatEngine:
    """AI智能问答引擎"""

    FUNCTION_KEYWORDS = {
        "menu": ["菜单", "功能", "帮助", "help", "支持", "可以做什么", "使用方法", "有哪些功能", "caidan", "cd"],
        "show_all": ["所有学生", "全部学生", "列表", "学生列表", "查看所有", "显示全部", "显示所有", "所有同学", "全部同学", "xianshi", "xs"],
        "add": ["添加", "新增", "录入", "加入", "增加学生", "添加学生", "录入学生", "新学生", "tianjia", "tj"],
        "delete": ["删除", "移除", "清除", "注销", "删除学生", "shanchu", "shanch", "sc", "del"],
        "update": ["修改", "更新", "编辑", "更改", "调整", "修改成绩", "改成绩", "xiugai", "xg"],
        "rank_total": ["总分排名", "全校排名", "总排名", "成绩排名", "排名榜", "paixu", "paix", "ranking", "rank"],
        "rank_class": ["班级排名", "班排名", "班里排名", "班级名次", "banpaixing", "班排行"],
        "rank_grade": ["年级排名", "级排名", "年级名次", "nianjipaixing"],
        "rank_subject": ["数学排名", "语文排名", "英语排名", "物理排名", "化学排名", "生物排名", "单科排名", "学科排名", "kemupaixing"],
        "evaluate_class": ["分析班", "评估班", "班级分析", "班级评估", "班级成绩", "班怎么样", "fenxi", "fx", "fxban"],
        "evaluate_grade": ["分析年级", "评估年级", "年级分析", "年级评估", "年级成绩", "fxni"],
        "evaluate_student": ["评估", "评价", "分析学生", "学生评估", "学生分析", "学习评估", "pinggu", "pg"],
        "stats": ["统计", "概览", "概况", "汇总", "报表", "系统统计", "tongji", "tj2"],
        "export_excel": ["导出", "导出excel", "excel", "导出表格", "下载", "daochu"],
        "table": ["查看表格", "数据表格", "编辑表格", "表格视图", "打开表格", "biaoge"],
        "greeting": ["你好", "您好", "hi", "hello", "嗨", "hey", "早上好", "晚上好", "下午好", "nihao", "niha"],
        "thanks": ["谢谢", "感谢", "多谢", "thanks", "thank", "辛苦了", "xiexie"],
        "exit": ["退出", "exit", "quit", "再见", "拜拜", "bye", "关机", "tuichu"],
    }

    def __init__(self, db: Database):
        self.db = db
        self.deepseek = DeepSeekAI()
        self.greetings = [
            "你好！我是智析云途AI助手，很高兴为你服务！\n\n试试说「菜单」查看所有功能，或直接输入问题~",
            "欢迎使用智析云途学生成绩管理系统！有什么可以帮助你的吗？",
            "你好呀！需要查询成绩还是做分析评估？我都可以帮你~"
        ]

    def fuzzy_match(self, text: str, keywords: List[str]) -> bool:
        text = text.replace(" ", "").lower()
        for kw in keywords:
            if kw.lower().replace(" ", "") in text:
                return True
        return False

    def extract_student_info(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        # 8位学号
        m = re.search(r'(?<!\d)(\d{8})(?!\d)', text)
        if m:
            return "student_id", m.group(1)
        # 姓名 (2-4个中文字符)
        m = re.search(r'[\u4e00-\u9fa5]{2,4}', text)
        if m:
            name = m.group(0)
            exclude = {"查询", "查找", "搜索", "添加", "新增", "删除", "修改",
                       "更新", "统计", "评估", "分析", "排名", "录入", "移除",
                       "退出", "菜单", "帮助", "列表", "名单", "学生", "成绩",
                       "老师", "同学", "班级", "年级", "我们", "你们", "他们",
                       "今天", "明天", "所有", "全部", "查看", "了解", "介绍",
                       "功能", "支持", "加油", "努力", "导出", "表格", "数据",
                       "系统", "学校", "科目", "语文", "数学", "英语", "物理",
                       "化学", "生物", "考试", "学习",
                       "建议", "点评", "总结", "报告", "显示", "打印", "保存",
                       "编辑", "搜索", "筛选", "排序",
                       "哪个", "什么", "怎么", "如何", "为什么", "多少",
                       "优秀", "良好", "中等", "及格", "不及格"}
            if name not in exclude:
                return "name", name
        return None, None

    def extract_class_info(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """提取班级信息，返回 (grade_code, class_code)"""
        for gname, gcode in GRADE_CODES.items():
            m = re.search(rf'{gname}\s*(\d{{1,2}})\s*班', text)
            if m:
                return gcode, m.group(1).zfill(2)
        # 尝试单独提取班级编号
        m = re.search(r'(0?[1-9]|[12]\d|30)\s*班', text)
        if m:
            classes = self.db.fetchall("SELECT DISTINCT grade_code FROM students")
            if classes:
                latest = max(c["grade_code"] for c in classes)
                return latest, m.group(1).zfill(2)
            return "01", m.group(1).zfill(2)
        return None, None

    def extract_grade_info(self, text: str) -> Optional[str]:
        for gname, gcode in GRADE_CODES.items():
            if gname in text:
                return gcode
        return None

    def _generate_menu(self) -> str:
        return (
            "【功能菜单】\n"
            "====================\n"
            "【信息】基础功能:\n"
            "  添加学生 - 添加新同学\n"
            "  查询学生 - 按学号/姓名查询\n"
            "  修改成绩 - 更新各科成绩\n"
            "  删除学生 - 移除学生\n"
            "  显示全部 - 浏览所有学生\n\n"
            "【图表】排名功能:\n"
            "  总分排名 - 全校总分排名\n"
            "  班级排名 - 某班内排名\n"
            "  年级排名 - 全年级排名\n"
            "  单科排名 - 某科目排名\n\n"
            "【AI】智能分析:\n"
            "  分析班级 - 综合评估班级\n"
            "  分析年级 - 整体分析年级\n"
            "  评估学生 - 个人学习评估\n"
            "  系统统计 - 数据概览\n\n"
            "【文件】数据管理:\n"
            "  导出Excel - 导出成绩表\n"
            "  查看表格 - 打开数据表格\n\n"
            "【提示】自然语言提问:\n"
            "  「高一1班成绩怎么样」\n"
            "  「分析张三的学习情况」\n"
            "  「系统统计」\n"
            "  「给我一些学习建议」\n"
            "===================="
        )

    def _preprocess_pinyin(self, text: str) -> str:
        """将拼音类关键词转为中文，增强自然语言匹配"""
        replacements = [
            ("gao yi", "高一"), ("gao1", "高一"), ("gaoyi", "高一"),
            ("gao er", "高二"), ("gao2", "高二"), ("gaoer", "高二"),
            ("gao san", "高三"), ("gao3", "高三"), ("gaosan", "高三"),
            ("ban", "班"),
            ("nian ji", "年级"), ("nianji", "年级"),
            ("ban ji", "班级"), ("banji", "班级"),
            ("pai ming", "排名"), ("paiming", "排名"), ("paixin", "排名"), ("pai m", "排名"),
            ("fen xi", "分析"), ("fenxi", "分析"), ("fx", "分析"),
            ("shan chu", "删除"), ("shanchu", "删除"), ("shancu", "删除"),
            ("xiu gai", "修改"), ("xiugai", "修改"), ("xugai", "修改"),
            ("tian jia", "添加"), ("tianjia", "添加"),
            ("zong fen", "总分"), ("zongfen", "总分"),
            ("xue sheng", "学生"), ("xuesheng", "学生"),
            ("cheng ji", "成绩"), ("chengji", "成绩"),
            ("ping gu", "评估"), ("pinggu", "评估"),
            ("cha xun", "查询"), ("chaxun", "查询"),
            ("tong ji", "统计"), ("tongji", "统计"),
            ("dao chu", "导出"), ("daochu", "导出"),
            ("bang zhu", "帮助"), ("bangzhu", "帮助"),
            ("xue hao", "学号"), ("xuehao", "学号"),
        ]
        lower = text.lower()
        result = text
        for pinyin_word, chinese in replacements:
            if pinyin_word in lower:
                idx = lower.find(pinyin_word)
                result = result[:idx] + chinese + result[idx + len(pinyin_word):]
                lower = result.lower()
        result = re.sub(r'\s+', '', result)
        result = result.replace('~', '')
        return result

    def process_query(self, user_input: str) -> Tuple[str, Optional[str], Any]:
        user_input = user_input.strip()
        if not user_input:
            return "请输入你想查询或操作的内容~", None, None

        user_input = self._preprocess_pinyin(user_input)

        # 1. 问候
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["greeting"]):
            return random.choice(self.greetings), None, None

        # 2. 菜单
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["menu"]):
            return self._generate_menu(), "menu", None

        # 3. 退出
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["exit"]):
            return "感谢使用智析云途！再见，祝你学习进步！", "exit", None

        # 4. 感谢
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["thanks"]):
            return random.choice([
                "不客气！很高兴能帮到你",
                "应该的！希望我的分析对你有帮助~",
                "随时为你服务！有需要尽管找我哦"
            ]), None, None

        # 5. 日常生活问题检测
        daily_patterns = [
            "天气", "温度", "下雨", "下雪", "晴天", "阴天",
            "笑话", "故事", "段子",
            "电影", "电视剧", "娱乐", "明星",
            "体育", "比赛", "足球", "篮球",
            "音乐", "歌曲",
            "新闻", "八卦", "热点",
            "吃饭", "美食", "好吃",
            "旅游", "景点", "好玩",
            "游戏", "打游戏", "王者", "吃鸡",
            "恋爱", "对象", "女朋友", "男朋友",
            "工作", "公司", "上班",
            "股票", "基金", "理财",
            "时间", "日期", "星期几",
            "年龄", "生日", "星座",
            "颜色", "喜欢什么",
            "演唱", "歌星", "演员",
            "好看", "好玩", "有趣",
            "中午吃", "晚上吃", "早餐",
            "你好吗", "在吗", "干嘛呢",
            "今天周", "现在几",
            "推荐", "介绍",
        ]
        if any(p in user_input for p in daily_patterns):
            return self._local_daily_response()

        # 6. 情感/鼓励
        chat_map = {
            "加油": "加油！学习是持续进步的过程，每一天的努力都会开花结果！",
            "努力": "天道酬勤，坚持就是胜利！",
            "奋斗": "奋斗的青春最美丽！有什么问题随时问我~",
            "迷茫": "每个人都会迷茫，不妨从小目标开始一步步来！",
            "难过": "抱抱你~ 调整好心态重新出发！",
            "开心": "开心就好！好心情学习效率更高哦~",
            "哈哈": "哈哈，学习也可以很有趣的！",
            "不错": "谢谢夸奖！我会继续努力提供更好的服务！",
            "厉害": "过奖啦！主要是数据本身就很棒~",
            "棒": "你最棒！",
            "心情": "心情影响学习效率，记得保持积极心态！",
            "辛苦了": "不辛苦！能帮到你我就很开心~",
            "学习": "学习使人进步！有什么科目需要帮助吗？",
            "建议": "学习建议：制定计划、定期复习、多做练习、不懂就问！",
            "你好棒": "谢谢你！你也很棒！一起加油！",
            "晚安": "晚安！好好休息，明天又是充满希望的一天！",
            "早上好": "早上好！新的一天，新的收获，加油！",
        }
        for keyword, response in chat_map.items():
            if keyword in user_input:
                return response, None, None

        # 导出Excel
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["export_excel"]):
            return "正在导出Excel文件...", "export_excel", None

        # 查看表格
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["table"]):
            return "正在打开数据表格...", "table", None

        # 显示全部学生
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["show_all"]):
            return "正在查询所有学生...", "show_all", None

        # 统计
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["stats"]):
            return "正在生成系统数据概览...", "stats", None

        # 总分排名
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["rank_total"]):
            return "正在查询全校总分排名...", "rank_total", None

        # 单科排名
        for subj in SUBJECTS:
            if f"{subj}排名" in user_input or f"{subj}排行" in user_input:
                gy, cn = self.extract_class_info(user_input)
                if gy and cn:
                    return f"正在查询{GRADE_NAMES.get(gy, gy)}{cn}班{subj}排名...", "rank_subject_class", (gy, cn, subj)
                return f"正在查询全校{subj}排名...", "rank_subject", subj

        # 班级排名
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["rank_class"]):
            gy, cn = self.extract_class_info(user_input)
            if gy and cn:
                return f"正在查询{GRADE_NAMES.get(gy, gy)}{cn}班排名...", "rank_class", (gy, cn)
            return "请指定班级，例如: 高一1班排名", "rank_class", None

        # 年级排名
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["rank_grade"]):
            gy = self.extract_grade_info(user_input)
            if gy:
                return f"正在查询{GRADE_NAMES.get(gy, gy)}排名...", "rank_grade", gy
            return "请指定年级，例如: 高一年级排名", "rank_grade", None

        # 班级分析
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["evaluate_class"]):
            gy, cn = self.extract_class_info(user_input)
            if gy and cn:
                return f"正在分析{GRADE_NAMES.get(gy, gy)}{cn}班成绩...", "evaluate_class", (gy, cn)
            return "请指定要分析的班级，例如: 分析高一1班成绩", "evaluate_class", None

        # 年级分析
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["evaluate_grade"]):
            gy = self.extract_grade_info(user_input)
            if gy:
                return f"正在分析{GRADE_NAMES.get(gy, gy)}成绩...", "evaluate_grade", gy
            return "请指定要分析的年级，例如: 分析高一年级成绩", "evaluate_grade", None

        # 添加学生
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["add"]):
            return ("好的！添加新同学~ 请使用格式:\n"
                   "添加学生 学号 姓名 性别 语文 数学 英语 物理 化学 生物\n"
                   "学号标准: 8位(GGCCNNNN) 如: 01010006\n"
                   "例如: 添加学生 01010099 王小明 男 75 82 90 68 85 79"), "add", None

        # 删除学生
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["delete"]):
            _, value = self.extract_student_info(user_input)
            if value:
                return f"确定要删除「{value}」？(需要确认)", "delete_confirm", value
            return "请提供要删除学生的学号或姓名", "delete", None

        # 修改成绩
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["update"]):
            m = re.search(r'修改\s*([\u4e00-\u9fa5]+)\s*(语文|数学|英语|物理|化学|生物)\s*(\d{1,3}(?:\.\d)?)', user_input)
            if m:
                name = m.group(1)
                subject = m.group(2)
                score = float(m.group(3))
                return f"正在修改{name}的{subject}成绩为{score}分...", "update_single", (name, subject, score)
            return ("请提供要修改的信息，例如:\n"
                   "修改 张三 数学 95\n"
                   "或: 修改成绩 01010001 85 90 88 76 92 81"), "update", None

        # 评估学生
        if self.fuzzy_match(user_input, self.FUNCTION_KEYWORDS["evaluate_student"]):
            _, value = self.extract_student_info(user_input)
            if value:
                return f"正在评估学生「{value}」的学习表现...", "evaluate_student", ("name" if re.match(r'^[\u4e00-\u9fa5]+$', value) and len(value) <= 4 else "student_id", value)
            return "请提供要评估的学生的学号或姓名", "evaluate_student", None

        # 智能检测班级/年级
        gy, cn = self.extract_class_info(user_input)
        if gy and cn:
            return f"正在分析{GRADE_NAMES.get(gy, gy)}{cn}班...", "evaluate_class", (gy, cn)

        gy = self.extract_grade_info(user_input)
        if gy:
            return f"正在分析{GRADE_NAMES.get(gy, gy)}整体情况...", "evaluate_grade", gy

        # 包含学生姓名，尝试查询
        _, value = self.extract_student_info(user_input)
        if value and len(user_input) < 30:
            return f"正在查询学生「{value}」的信息...", "query_student", ("name" if re.match(r'^[\u4e00-\u9fa5]+$', value) and len(value) <= 4 else "student_id", value)

        # 默认: 调用 DeepSeek API
        return self._generate_ai_response(user_input)

    def _generate_ai_response(self, user_input: str) -> Tuple[str, Optional[str], Any]:
        db_context = self.deepseek.build_context(self.db)
        system_prompt = self.deepseek.get_system_prompt(db_context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        if self.deepseek.available:
            try:
                response = self.deepseek.chat(messages, temperature=0.8, max_tokens=800)
                if response:
                    return f"[AI] {response}", "ai_response", None
            except Exception as e:
                print(f"[AI] API调用失败: {e}")

        return self._local_fallback_response(user_input)

    def _local_daily_response(self) -> Tuple[str, Optional[str], Any]:
        """日常生活问题 - 简短回复 + 系统功能说明"""
        count = self.db.fetchone("SELECT COUNT(*) as cnt FROM students")
        total = count["cnt"] if count else 0

        daily_responses = [
            f"哈哈，这个我不太擅长~ 我是智析云途学生成绩管理系统，主要负责成绩管理、学籍管理、排名分析等。查成绩、做评估找我准没错！",
            f"这个问题超出我的范围啦~ 我是专业的学生成绩管理系统，专注于学籍管理、成绩录入、班级/年级排名分析哦！有什么成绩相关问题可以问我~",
            f"这个嘛...我是学习成绩管理AI，主要做数据库管理、成绩分析的。系统里现有{total}位同学的数据，想看看哪个班的成绩？",
            f"嘿嘿，日常聊天不是我的主业啦~ 我是智析云途学生成绩管理系统，帮你查成绩、做分析、排名评估都在行！",
            f"这个我不太会~ 不过说到成绩、排名、分析这些我可在行！我是专业的学生成绩管理系统，有{total}位同学的数据等你来探索哦~",
        ]
        return random.choice(daily_responses), None, None

    def _local_fallback_response(self, user_input: str) -> Tuple[str, Optional[str], Any]:
        """本地回退处理 - 无法理解的问题"""
        count = self.db.fetchone("SELECT COUNT(*) as cnt FROM students")
        total = count["cnt"] if count else 0

        fallbacks = [
            f"嗯...我暂时不太理解你的问题呢。\n"
            f"不过目前系统中有 {total} 位同学的记录，你可以试试以下操作：\n"
            f"  说「菜单」查看所有功能\n"
            f"  说「分析 某班」查看班级成绩\n"
            f"  说「查询 学生姓名」查找学生\n"
            " 本系统主要提供学生成绩数据库管理服务",

            f"抱歉，我没有完全理解你的意思。\n"
            f"目前系统管理着 {total} 位同学的数据，\n"
            "你可以试试这样说：\n"
            "  「高一1班成绩怎么样」\n"
            "  「查询张三的成绩」\n"
            "  「显示系统统计」\n"
            " 我是学生成绩管理系统，以上功能都可以帮到你~",

            f"让我看看... 系统中有 {total} 位同学。\n"
            "要不你换个说法？或者直接说「菜单」看看我能做什么~\n"
            " 本系统核心功能是学生成绩数据库管理哦！"
        ]
        return random.choice(fallbacks), None, None


# ===================== PyQt5 图形界面 =====================

def get_font(size=11, bold=False):
    f = QFont("Microsoft YaHei", size)
    f.setBold(bold)
    return f


class LoginDialog(QDialog):
    """登录对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("智析云途 - 登录")
        self.setFixedSize(420, 320)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #667eea, stop:1 #764ba2);
            }
            QLabel {
                color: white;
                font-size: 15px;
                padding: 4px;
            }
            QLineEdit {
                padding: 10px 14px;
                font-size: 15px;
                border: 2px solid rgba(255,255,255,0.3);
                border-radius: 6px;
                background: rgba(255,255,255,0.9);
                color: #333;
                min-height: 20px;
            }
            QLineEdit:focus {
                border-color: #fff;
                background: white;
            }
            QPushButton {
                padding: 12px 30px;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                background: rgba(255,255,255,0.9);
                color: #667eea;
                min-height: 20px;
            }
            QPushButton:hover {
                background: white;
            }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(40, 30, 40, 30)

        title = QLabel("智析云途")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_font(26, True))
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: white; margin-bottom: 5px;")
        layout.addWidget(title)

        subtitle = QLabel("AI智能学生成绩管理系统")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(get_font(13))
        subtitle.setStyleSheet("font-size: 13px; color: rgba(255,255,255,0.8); margin-bottom: 12px;")
        layout.addWidget(subtitle)

        self.username = QLineEdit()
        self.username.setPlaceholderText("用户名")
        self.username.setText("admin")
        self.username.setFont(get_font(14))
        layout.addWidget(self.username)

        self.password = QLineEdit()
        self.password.setPlaceholderText("密码")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setText("123456")
        self.password.setFont(get_font(14))
        layout.addWidget(self.password)

        btn = QPushButton("登 录")
        btn.clicked.connect(self.check_login)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFont(get_font(14, True))
        layout.addWidget(btn)

        hint = QLabel("默认账号: admin / 123456")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFont(get_font(11))
        hint.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.6);")
        layout.addWidget(hint)

        layout.addStretch()
        self.setLayout(layout)
        self.password.returnPressed.connect(self.check_login)

    def check_login(self):
        if self.username.text() == _LOGIN_USERNAME and self.password.text() == _LOGIN_PASSWORD:
            self.accept()
        else:
            QMessageBox.warning(self, "登录失败", "用户名或密码错误！")


class AIWorker(QThread):
    """AI后台工作线程"""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, deepseek: DeepSeekAI, messages: List[Dict], temperature=0.7):
        super().__init__()
        self.deepseek = deepseek
        self.messages = messages
        self.temperature = temperature
        self._is_running = True

    def run(self):
        try:
            response = self.deepseek.chat(self.messages, temperature=self.temperature)
            if not self._is_running:
                return
            if response:
                self.finished.emit(response)
            else:
                self.error.emit("AI未能生成回复，请稍后重试")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"AI处理出错: {str(e)}")

    def safe_stop(self):
        self._is_running = False


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.db = Database()
        self.evaluator = GradeEvaluator()
        self.ai_engine = AIChatEngine(self.db)
        self._busy = False
        self._ai_workers = []

        loaded, skipped, load_errors = self.db.load_from_txt()
        if loaded > 0:
            print(f"[系统] 从数据文件加载了 {loaded} 条记录")
            if skipped > 0:
                print(f"[系统] 跳过 {skipped} 条无效记录")
                for err in load_errors[:5]:
                    print(f"  [跳过] {err}")

        self._verify_ranks()
        self._init_ui()

    def _verify_ranks(self):
        try:
            unranked = self.db.fetchone("SELECT COUNT(*) as cnt FROM students WHERE class_rank=-1 OR grade_rank=-1")
            if unranked and unranked["cnt"] > 0:
                print(f"[系统] 发现 {unranked['cnt']} 条未排名数据，正在更新...")
                self.db.update_all_ranks()
        except Exception as e:
            print(f"[系统] 排名验证失败: {e}")

    def _init_ui(self):
        self.setWindowTitle("智析云途 - AI智能学生成绩管理系统")
        self.setMinimumSize(1200, 820)

        self.setStyleSheet("""
            QMainWindow { background: #f0f2f5; }
            QTextEdit {
                background: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QLineEdit {
                padding: 10px 15px;
                font-size: 14px;
                border: 2px solid #e0e0e0;
                border-radius: 20px;
                background: white;
            }
            QLineEdit:focus { border-color: #667eea; }
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                background: #667eea;
                color: white;
            }
            QPushButton:hover { background: #5a6fd6; }
            QPushButton:pressed { background: #4a5fc6; }
            QTableWidget {
                background: white;
                border: 1px solid #ddd;
                border-radius: 6px;
                gridline-color: #eee;
                font-size: 13px;
            }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:selected { background: #667eea; color: white; }
            QHeaderView::section {
                background: #667eea;
                color: white;
                padding: 8px;
                border: none;
                font-weight: bold;
                font-size: 13px;
            }
            QComboBox {
                padding: 6px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
                font-size: 13px;
                min-height: 20px;
            }
            QComboBox:hover { border-color: #667eea; }
            QComboBox::drop-down { border: none; width: 24px; }
            QSplitter::handle { background: #ddd; width: 3px; }
            QStatusBar { background: #e8eaf6; border-top: 1px solid #ddd; }
        """)

        self._setup_ui()
        self._refresh_table()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #667eea, stop:1 #764ba2); border-radius: 10px;")
        title_layout = QHBoxLayout()

        title_label = QLabel("【智析云途】AI智能学生成绩管理系统")
        title_label.setFont(get_font(16, True))
        title_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold; padding: 8px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        btn_style = ("QPushButton { background: rgba(255,255,255,0.2); color: white; padding: 6px 12px; "
                     "font-size: 12px; border-radius: 4px; min-height: 18px; } "
                     "QPushButton:hover { background: rgba(255,255,255,0.3); }")

        buttons = [
            ("显示全部", self.show_all),
            ("总分排名", self.show_rank_total),
            ("班级排名", self.show_rank_class),
            ("年级排名", self.show_rank_grade),
            ("导出Excel", self.export_excel),
            ("表格视图", self.open_table_dialog),
            ("菜单", self.show_menu),
        ]

        for text, handler in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(btn_style)
            btn.setFont(get_font(12))
            btn.clicked.connect(handler)
            title_layout.addWidget(btn)

        title_bar.setLayout(title_layout)
        main_layout.addWidget(title_bar)

        # 分割器
        splitter = QSplitter(Qt.Vertical)

        # 上方: 聊天区域
        chat_widget = QWidget()
        chat_layout = QVBoxLayout()
        chat_layout.setSpacing(6)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setMinimumHeight(180)
        self.chat_area.setFont(get_font(14))
        chat_layout.addWidget(self.chat_area)

        input_layout = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入指令或问题，按Enter发送...")
        self.input_box.setFont(get_font(14))
        self.input_box.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_box)

        send_btn = QPushButton("发送")
        send_btn.setFont(get_font(14, True))
        send_btn.setStyleSheet("""
            QPushButton { padding: 10px 24px; font-size: 14px; border-radius: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #667eea, stop:1 #764ba2);
                color: white; font-weight: bold; min-height: 16px; }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6fd6, stop:1 #6a41a2); }
        """)
        send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(send_btn)
        chat_layout.addLayout(input_layout)

        chat_widget.setLayout(chat_layout)
        splitter.addWidget(chat_widget)

        # 下方: 可编辑数据表格
        table_widget = QWidget()
        table_layout = QVBoxLayout()
        table_layout.setSpacing(4)
        table_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("年级:"))
        self.table_grade_filter = QComboBox()
        self.table_grade_filter.addItem("全部年级")
        self._update_grade_filter()
        self.table_grade_filter.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.table_grade_filter)

        toolbar.addWidget(QLabel("班级:"))
        self.table_class_filter = QComboBox()
        self.table_class_filter.addItem("全部班级")
        self.table_class_filter.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.table_class_filter)
        toolbar.addStretch()

        refresh_btn = QPushButton("刷新表格")
        refresh_btn.setFont(get_font(12))
        refresh_btn.clicked.connect(self._refresh_table)
        toolbar.addWidget(refresh_btn)

        save_btn = QPushButton("保存修改")
        save_btn.setFont(get_font(12))
        save_btn.clicked.connect(self._save_table_changes)
        toolbar.addWidget(save_btn)

        add_btn = QPushButton("添加学生")
        add_btn.setFont(get_font(12))
        add_btn.clicked.connect(self._show_add_dialog)
        toolbar.addWidget(add_btn)

        toolbar.addWidget(self._make_delete_btn())
        table_layout.addLayout(toolbar)

        # 表格
        self.data_table = QTableWidget()
        self.data_table.setColumnCount(13)
        self.data_table.setHorizontalHeaderLabels(
            ["学号", "姓名", "性别", "年级", "班级", "语文", "数学", "英语", "物理", "化学", "生物", "总分", "操作"]
        )
        self.data_table.horizontalHeader().setStretchLastSection(False)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.data_table.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeToContents)
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.data_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.data_table.setSortingEnabled(True)
        self.data_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.data_table.customContextMenuRequested.connect(self._on_table_right_click)
        table_layout.addWidget(self.data_table)

        self.table_stats = QLabel()
        self.table_stats.setFont(get_font(13))
        self.table_stats.setStyleSheet("padding: 8px; background: white; border: 1px solid #ddd; border-radius: 4px; font-size: 13px;")
        table_layout.addWidget(self.table_stats)

        table_widget.setLayout(table_layout)
        splitter.addWidget(table_widget)
        splitter.setSizes([300, 400])
        main_layout.addWidget(splitter)

        self.status_bar = QStatusBar()
        self.status_bar.setFont(get_font(12))
        self.status_bar.showMessage("就绪")
        main_layout.addWidget(self.status_bar)

        central.setLayout(main_layout)
        self._append_message("system", "欢迎使用智析云途AI智能学生成绩管理系统！\n输入「菜单」查看所有功能，或直接输入问题开始智能对话。\n下方表格可直接双击编辑成绩，点击「保存修改」生效。")

    def _update_grade_filter(self):
        current = self.table_grade_filter.currentText()
        self.table_grade_filter.blockSignals(True)
        while self.table_grade_filter.count() > 1:
            self.table_grade_filter.removeItem(1)
        try:
            grades = self.db.get_available_grades()
            for g in grades:
                name = GRADE_NAMES.get(g, f"{g}年级")
                self.table_grade_filter.addItem(f"{name}({g})")
            idx = self.table_grade_filter.findText(current)
            self.table_grade_filter.setCurrentIndex(idx if idx >= 0 else 0)
        except Exception:
            pass
        self.table_grade_filter.blockSignals(False)

    def _update_class_filter(self, grade_code=None):
        current = self.table_class_filter.currentText()
        self.table_class_filter.blockSignals(True)
        while self.table_class_filter.count() > 1:
            self.table_class_filter.removeItem(1)
        try:
            if grade_code:
                classes = self.db.get_available_classes(grade_code)
            else:
                classes = self.db.get_available_classes()
            for c in classes:
                self.table_class_filter.addItem(f"{c}班")
            idx = self.table_class_filter.findText(current)
            self.table_class_filter.setCurrentIndex(idx if idx >= 0 else 0)
        except Exception:
            pass
        self.table_class_filter.blockSignals(False)

    def _on_filter_changed(self):
        grade_text = self.table_grade_filter.currentText()
        grade_code = None
        for gname, gcode in GRADE_CODES.items():
            if gname in grade_text:
                grade_code = gcode
                break
        self._update_class_filter(grade_code)
        self._refresh_table()

    def _make_delete_btn(self) -> QPushButton:
        btn = QPushButton("删除选中")
        btn.setFont(get_font(12))
        btn.setStyleSheet(
            "QPushButton { background: #e74c3c; color: white; padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background: #c0392b; }"
        )
        btn.clicked.connect(self._delete_selected_student)
        return btn

    def _on_table_right_click(self, pos: QPoint):
        row = self.data_table.rowAt(pos.y())
        if row < 0:
            return
        self.data_table.selectRow(row)

        student_id_item = self.data_table.item(row, 0)
        name_item = self.data_table.item(row, 1)
        if not student_id_item or not name_item:
            return
        sid, name = student_id_item.text(), name_item.text()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #ddd; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 8px 20px; font-size: 13px; }
            QMenu::item:selected { background: #667eea; color: white; border-radius: 4px; }
        """)

        action_delete = QAction(f"删除 {name}({sid})", self)
        action_delete.triggered.connect(lambda: self._confirm_delete(sid, name))
        menu.addAction(action_delete)
        menu.addSeparator()

        action_edit = QAction(f"修改 {name} 的成绩", self)
        action_edit.triggered.connect(lambda: self._edit_student_score(sid, name))
        menu.addAction(action_edit)
        menu.addSeparator()

        action_eval = QAction(f"评估 {name}", self)
        action_eval.triggered.connect(lambda: self._evaluate_student_from_table(sid, name))
        menu.addAction(action_eval)

        menu.exec_(self.data_table.viewport().mapToGlobal(pos))

    def _confirm_delete(self, sid: str, name: str):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除学生「{name}」(学号: {sid}) 吗？\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.execute("DELETE FROM students WHERE student_id=?", (sid,))
                self.db.update_all_ranks()
                self._append_message("system", f"已删除学生「{name}」({sid})")
                self._refresh_table()
                self.status_bar.showMessage(f"已删除 {name}")
            except Exception as e:
                QMessageBox.warning(self, "删除失败", str(e))

    def _delete_selected_student(self):
        selected = self.data_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请先在表格中选中要删除的学生行")
            return
        row = selected[0].row()
        student_id_item = self.data_table.item(row, 0)
        name_item = self.data_table.item(row, 1)
        if student_id_item and name_item:
            self._confirm_delete(student_id_item.text(), name_item.text())

    def _edit_student_score(self, sid: str, name: str):
        student = self.db.fetchone("SELECT * FROM students WHERE student_id=?", (sid,))
        if not student:
            QMessageBox.warning(self, "错误", f"未找到学生 {sid}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"修改 {name} 的成绩")
        dialog.setFixedSize(350, 320)
        dialog.setStyleSheet("""
            QDialog { background: white; }
            QLabel { font-size: 14px; padding: 4px; }
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ddd; border-radius: 4px; }
            QPushButton { padding: 8px 20px; font-size: 14px; border: none; border-radius: 4px; background: #667eea; color: white; }
            QPushButton:hover { background: #5a6fd6; }
        """)

        layout = QVBoxLayout()
        form = QFormLayout()
        inputs = {}
        for subj, field in zip(SUBJECTS, SUBJECT_FIELDS):
            inp = QLineEdit()
            inp.setPlaceholderText(f"当前: {int(student[field])}")
            inputs[field] = inp
            form.addRow(f"{subj}:", inp)

        layout.addLayout(form)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("保存修改")
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("QPushButton { background: #95a5a6; } QPushButton:hover { background: #7f8c8d; }")
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(lambda: self._do_edit_score(dialog, sid, inputs))
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        dialog.setLayout(layout)
        dialog.exec_()

    def _do_edit_score(self, dialog: QDialog, sid: str, inputs: Dict[str, QLineEdit]):
        scores = []
        for field in SUBJECT_FIELDS:
            val = inputs[field].text().strip()
            if val:
                try:
                    s = float(val)
                    if s < 0 or s > 100:
                        QMessageBox.warning(dialog, "错误", "成绩必须在0-100之间")
                        return
                    scores.append(s)
                except ValueError:
                    QMessageBox.warning(dialog, "错误", "请输入有效的数字")
                    return
            else:
                scores.append(None)

        updates = []
        params = []
        for field, score in zip(SUBJECT_FIELDS, scores):
            if score is not None:
                updates.append(f"{field}=?")
                params.append(score)

        if not updates:
            QMessageBox.information(dialog, "提示", "没有需要修改的成绩")
            return

        params.append(sid)
        try:
            self.db.execute(
                f"UPDATE students SET {', '.join(updates)}, total_score=chinese+math+english+physics+chemistry+biology WHERE student_id=?",
                params
            )
            self.db.update_all_ranks()
            self._refresh_table()
            self._append_message("system", f"已更新 {sid} 的成绩")
            self.status_bar.showMessage(f"已修改 {sid} 的成绩")
            dialog.accept()
        except Exception as e:
            QMessageBox.warning(dialog, "错误", f"修改失败: {e}")

    def _evaluate_student_from_table(self, sid: str, name: str):
        self.input_box.setText(f"评估 {name}")
        self.send_message()

    def _refresh_table(self):
        try:
            self.data_table.itemChanged.disconnect()
        except:
            pass

        self.data_table.setSortingEnabled(False)

        grade_text = self.table_grade_filter.currentText()
        class_text = self.table_class_filter.currentText()

        sql = "SELECT * FROM students"
        conditions = []

        for gname, gcode in GRADE_CODES.items():
            if gname in grade_text and "全部" not in grade_text:
                conditions.append(f"grade_code='{gcode}'")
                break

        if class_text != "全部班级":
            try:
                class_code = class_text[:2]
                conditions.append(f"class_code='{class_code}'")
            except:
                pass

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY grade_code, class_code, student_id"

        students = self.db.fetchall(sql)
        self.data_table.setRowCount(len(students))

        for row, s in enumerate(students):
            gn = GRADE_NAMES.get(s["grade_code"], s["grade_code"])
            items = [
                s["student_id"], s["name"], s["gender"], gn,
                f"{s['class_code']}班",
                str(int(s["chinese"])), str(int(s["math"])), str(int(s["english"])),
                str(int(s["physics"])), str(int(s["chemistry"])), str(int(s["biology"])),
                str(int(s["total_score"])), "[删除]"
            ]

            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if 5 <= col <= 10:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setBackground(QColor(240, 255, 240))
                elif col == 12:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(QBrush(QColor("#e74c3c")))
                    item.setToolTip("点击此处删除该学生")
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.data_table.setItem(row, col, item)

        if students:
            totals = [s["total_score"] for s in students]
            avg = sum(totals) / len(totals)
            self.table_stats.setText(
                f"共 {len(students)} 名学生 | "
                f"总分范围: {min(totals):.0f} - {max(totals):.0f} | "
                f"平均分: {avg:.1f} | "
                f"双击成绩单元格可编辑，点击「保存修改」生效"
            )
        else:
            self.table_stats.setText("暂无数据")

        self._table_modified = {}
        self.data_table.setSortingEnabled(True)
        self.data_table.itemChanged.connect(self._on_table_cell_changed)

    def _on_table_cell_changed(self, item):
        row = item.row()
        col = item.column()

        if 5 <= col <= 10:
            try:
                val = float(item.text())
                if val < 0 or val > 100:
                    QMessageBox.warning(self, "无效输入", "成绩必须在0-100之间")
                    self._refresh_table()
                    return

                scores = []
                for c in range(5, 11):
                    cell = self.data_table.item(row, c)
                    if cell:
                        try:
                            scores.append(float(cell.text()))
                        except:
                            scores.append(0)
                    else:
                        scores.append(0)

                total = sum(scores)
                total_item = self.data_table.item(row, 11)
                if total_item:
                    total_item.setText(str(int(total)))

                student_id_item = self.data_table.item(row, 0)
                if student_id_item:
                    sid = student_id_item.text()
                    self._table_modified[sid] = {'scores': scores, 'total': total, 'row': row}

            except ValueError:
                pass

    def _save_table_changes(self):
        if not hasattr(self, '_table_modified') or not self._table_modified:
            QMessageBox.information(self, "提示", "没有需要保存的修改")
            return

        try:
            count = 0
            for sid, data in self._table_modified.items():
                scores = data['scores']
                total = data['total']
                self.db.execute(
                    "UPDATE students SET chinese=?, math=?, english=?, physics=?, chemistry=?, biology=?, total_score=? WHERE student_id=?",
                    (scores[0], scores[1], scores[2], scores[3], scores[4], scores[5], total, sid)
                )
                count += 1

            self.db.update_all_ranks()
            self._table_modified = {}

            QMessageBox.information(self, "成功", f"已保存 {count} 名学生的修改，并更新了排名")
            self._refresh_table()
            self._append_message("system", f"已保存 {count} 名学生的成绩修改并更新排名")
            self.status_bar.showMessage(f"已保存 {count} 条修改")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存时出错: {e}")

    def _show_add_dialog(self):
        try:
            dialog = AddStudentDialog(self.db, self)
            if dialog.exec_() == QDialog.Accepted:
                self._refresh_table()
                self._update_grade_filter()
                self._append_message("system", f"已成功添加学生 {dialog.student_id}")
        except Exception as e:
            QMessageBox.warning(self, "添加失败", f"添加学生时出错: {e}")

    def _append_message(self, sender: str, message: str):
        try:
            color = "#667eea" if sender == "user" else "#2ecc71" if sender == "system" else "#333"
            bg = "#f0f2ff" if sender == "user" else "#f0fff4" if sender == "system" else "white"
            html = f'<div style="margin: 6px 0; padding: 12px; border-radius: 8px; background: {bg}; border-left: 4px solid {color};">'
            if sender == "user":
                html += f'<b style="color: {color}; font-size: 14px;">你: </b>'
            html += f'<span style="color: #333; font-size: 14px; white-space: pre-wrap;">{message}</span></div>'
            self.chat_area.append(html)
            scrollbar = self.chat_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    def send_message(self, text_override=None):
        if self._busy:
            return
        self._busy = True

        try:
            if text_override:
                text = text_override
            else:
                text = self.input_box.text().strip()

            if not text:
                self._busy = False
                return

            self.input_box.clear()
            self._append_message("user", text)
            self.status_bar.showMessage("正在处理...")

            try:
                response, func, params = self.ai_engine.process_query(text)
            except Exception as e:
                self._append_message("system", f"AI分析出错: {e}")
                self.status_bar.showMessage("就绪")
                self._busy = False
                return

            if func == "exit":
                self._append_message("system", response)
                self._busy = False
                QTimer.singleShot(1000, self.close)
                return

            result_text_to_output = response
            try:
                result_text = self._execute_function(func, params, text)
                if result_text is not None:
                    result_text_to_output = result_text
            except Exception as e:
                result_text_to_output = f"操作出错: {e}"

            try:
                self._append_message("system", result_text_to_output)
            except Exception:
                pass

            try:
                if func in ("evaluate_class", "evaluate_grade", "evaluate_student", "rank_total", "stats"):
                    self._generate_ai_comment(func, params, text)
            except Exception:
                pass

            self.status_bar.showMessage("就绪")
        except Exception as e:
            try:
                self._append_message("system", f"系统错误: {e}")
                self.status_bar.showMessage("就绪")
            except:
                pass
            print(f"[send_message] Error: {traceback.format_exc()}")
        finally:
            QTimer.singleShot(100, lambda: setattr(self, '_busy', False))

    def _execute_function(self, func: Optional[str], params: Any, original_text: str) -> Optional[str]:
        if func is None:
            return None

        _funcs_needing_params = {
            "rank_class", "rank_grade", "rank_subject", "rank_subject_class",
            "evaluate_class", "evaluate_grade", "evaluate_student",
            "query_student", "update_single", "delete_confirm"
        }
        if func in _funcs_needing_params and params is None:
            return None

        try:
            if func == "menu":
                return None

            elif func == "show_all":
                students = self.db.fetchall("SELECT * FROM students ORDER BY grade_code, class_code, student_id")
                if not students:
                    return "[空] 系统中暂无学生数据。"
                lines = [f"共 {len(students)} 位同学:"]
                for s in students:
                    level = self.evaluator.get_grade_level(s["total_score"] / 6)
                    gn = GRADE_NAMES.get(s["grade_code"], s["grade_code"])
                    lines.append(f"  {s['student_id']} {s['name']} | {gn}{s['class_code']}班 | 总分:{s['total_score']:.0f} ({level})")
                return "\n".join(lines)

            elif func == "query_student":
                id_type, id_value = params
                student = self.db.fetchone(
                    "SELECT * FROM students WHERE student_id=? OR name=? LIMIT 1",
                    (id_value, id_value)
                )
                if student:
                    eval_result = self.evaluator.evaluate_student(student)
                    return self._format_student_detail(eval_result)
                return f"未找到「{id_value}」相关信息"

            elif func == "rank_total":
                students = self.db.fetchall("SELECT * FROM students ORDER BY total_score DESC")
                if not students:
                    return "[空] 暂无数据"
                lines = ["【全校总分排名】"]
                for i, s in enumerate(students, 1):
                    level = self.evaluator.get_grade_level(s["total_score"] / 6)
                    gn = GRADE_NAMES.get(s["grade_code"], s["grade_code"])
                    lines.append(f"  #{i:>2} {s['name']:<6} {gn}{s['class_code']}班 | {s['total_score']:.0f}分 ({level})")
                return "\n".join(lines)

            elif func == "rank_class":
                gy, cn = params
                students = self.db.fetchall(
                    "SELECT * FROM students WHERE grade_code=? AND class_code=? ORDER BY total_score DESC",
                    (gy, cn)
                )
                gn = GRADE_NAMES.get(gy, gy)
                if not students:
                    return f"{gn}{cn}班暂无数据"
                lines = [f"【{gn}{cn}班 排名】"]
                for i, s in enumerate(students, 1):
                    level = self.evaluator.get_grade_level(s["total_score"] / 6)
                    lines.append(f"  #{i:>2} {s['name']:<6} {s['total_score']:.0f}分 ({level})")
                avg = sum(s['total_score'] for s in students) / len(students)
                lines.append(f"  共 {len(students)} 人，班级平均分: {avg:.1f}")
                return "\n".join(lines)

            elif func == "rank_grade":
                gy = params
                students = self.db.fetchall(
                    "SELECT * FROM students WHERE grade_code=? ORDER BY total_score DESC",
                    (gy,)
                )
                gn = GRADE_NAMES.get(gy, gy)
                if not students:
                    return f"{gn}暂无数据"
                lines = [f"【{gn} 排名】"]
                for i, s in enumerate(students, 1):
                    level = self.evaluator.get_grade_level(s["total_score"] / 6)
                    lines.append(f"  #{i:>2} {s['name']:<6} {s['class_code']}班 | {s['total_score']:.0f}分 ({level})")
                return "\n".join(lines)

            elif func == "rank_subject":
                subject = params
                idx = SUBJECTS.index(subject)
                field = SUBJECT_FIELDS[idx]
                students = self.db.fetchall(f"SELECT * FROM students ORDER BY {field} DESC")
                if not students:
                    return "[空] 暂无数据"
                lines = [f"【全校{subject}排名】"]
                for i, s in enumerate(students, 1):
                    level = self.evaluator.get_grade_level(s[field])
                    gn = GRADE_NAMES.get(s["grade_code"], s["grade_code"])
                    lines.append(f"  #{i:>2} {s['name']:<6} {gn}{s['class_code']}班 | {s[field]:.0f}分 ({level})")
                return "\n".join(lines)

            elif func == "rank_subject_class":
                gy, cn, subject = params
                idx = SUBJECTS.index(subject)
                field = SUBJECT_FIELDS[idx]
                students = self.db.fetchall(
                    f"SELECT * FROM students WHERE grade_code=? AND class_code=? ORDER BY {field} DESC",
                    (gy, cn)
                )
                gn = GRADE_NAMES.get(gy, gy)
                if not students:
                    return f"{gn}{cn}班暂无数据"
                lines = [f"【{gn}{cn}班{subject}排名】"]
                for i, s in enumerate(students, 1):
                    level = self.evaluator.get_grade_level(s[field])
                    lines.append(f"  #{i:>2} {s['name']:<6} {s[field]:.0f}分 ({level})")
                return "\n".join(lines)

            elif func == "evaluate_class":
                gy, cn = params
                result = self.evaluator.evaluate_class(self.db, gy, cn)
                if not result:
                    gn = GRADE_NAMES.get(gy, gy)
                    return f"{gn}{cn}班暂无数据"
                return self._format_class_eval(result)

            elif func == "evaluate_grade":
                gy = params
                result = self.evaluator.evaluate_grade(self.db, gy)
                if not result:
                    gn = GRADE_NAMES.get(gy, gy)
                    return f"{gn}暂无数据"
                return self._format_grade_eval(result)

            elif func == "evaluate_student":
                id_type, id_value = params
                student = self.db.fetchone(
                    f"SELECT * FROM students WHERE {id_type}=? LIMIT 1",
                    (id_value,)
                )
                if student:
                    eval_result = self.evaluator.evaluate_student(student)
                    return self._format_student_eval(eval_result)
                return f"未找到「{id_value}」相关信息"

            elif func == "stats":
                return self._format_stats()

            elif func == "update_single":
                name, subject, score = params
                student = self.db.fetchone("SELECT * FROM students WHERE name=? LIMIT 1", (name,))
                if not student:
                    return f"未找到学生「{name}」"
                idx = SUBJECTS.index(subject)
                field = SUBJECT_FIELDS[idx]
                self.db.execute(
                    f"UPDATE students SET {field}=?, total_score=chinese+math+english+physics+chemistry+biology WHERE name=?",
                    (score, name)
                )
                self.db.update_all_ranks()
                student = self.db.fetchone("SELECT * FROM students WHERE name=? LIMIT 1", (name,))
                self._refresh_table()
                return f"已修改 {name} 的{subject}成绩为{score}分！新总分: {student['total_score']:.0f}"

            elif func == "export_excel":
                self.export_excel()
                return None

            elif func == "table":
                self.open_table_dialog()
                return None

            elif func == "add":
                return None

            elif func == "delete_confirm":
                _, value = params
                reply = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除「{value}」吗？此操作不可恢复！",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    student = self.db.fetchone(
                        "SELECT * FROM students WHERE student_id=? OR name=? LIMIT 1",
                        (value, value)
                    )
                    if student:
                        self.db.execute("DELETE FROM students WHERE id=?", (student["id"],))
                        self.db.update_all_ranks()
                        self._refresh_table()
                        return f"已删除学生「{student['name']}」"
                    return f"未找到「{value}」"
                return "已取消删除"

            elif func == "ai_response":
                return None

        except Exception as e:
            return f"操作出错: {str(e)}\n{traceback.format_exc()[:200]}"

        return None

    def _format_student_detail(self, eval_result: Dict) -> str:
        lines = [
            f"【{eval_result['name']} 详细信息】",
            f"学号: {eval_result['student_id']}",
            f"班级: {eval_result['grade']}",
            f"总分: {eval_result['total']:.0f} | 均分: {eval_result['average']}",
            f"等级: {eval_result['level']}",
            f"班级排名: #{eval_result['class_rank']} | 年级排名: #{eval_result['grade_rank']}",
            "-------- 各科成绩 --------"
        ]
        for d in eval_result['details']:
            bar = "#" * int(d['score'] // 10)
            lines.append(f"  {d['subject']}: {d['score']:.0f}分 {bar} ({d['level']})")
        lines.append(f"\n评语: {eval_result['comments']}")
        return "\n".join(lines)

    def _format_student_eval(self, eval_result: Dict) -> str:
        lines = [
            f"【{eval_result['name']} 学习评估报告】",
            f"班级: {eval_result['grade']}",
            f"总分: {eval_result['total']:.0f} | 均分: {eval_result['average']}",
            f"等级: {eval_result['level']}",
            f"班级排名: #{eval_result['class_rank']} | 年级排名: #{eval_result['grade_rank']}",
            "-------- 各科详情 --------"
        ]
        for d in eval_result['details']:
            lines.append(f"  {d['subject']}: {d['score']:.0f}分 ({d['level']})")
        if eval_result['strong_subjects']:
            lines.append(f"\n优势科目: {'、'.join(eval_result['strong_subjects'])}")
        if eval_result['weak_subjects']:
            lines.append(f"待加强: {'、'.join(eval_result['weak_subjects'])}")
        lines.append(f"\n评语:\n{eval_result['comments']}")
        return "\n".join(lines)

    def _format_class_eval(self, result: Dict) -> str:
        lines = [
            f"【{result['grade']} 成绩分析报告】",
            f"学生人数: {result['student_count']} 人",
            f"班级均分: {result['class_avg']} 分",
            f"及格率(>=360分): {result['pass_count']}/{result['student_count']} ({result['pass_count']/result['student_count']*100:.0f}%)",
            f"优秀率(均分>=90): {result['excellent_count']}/{result['student_count']} ({result['excellent_count']/result['student_count']*100:.0f}%)",
            "-------- 各科平均分 --------"
        ]
        for subj, avg in result['subject_averages'].items():
            level = self.evaluator.get_grade_level(avg)
            lines.append(f"  {subj}: {avg}分 ({level})")

        lines.append("-------- 等级分布 --------")
        for level, count in result['level_distribution'].items():
            bar = "#" * count
            if count > 0:
                lines.append(f"  {level}: {count}人 {bar}")

        lines.append(f"\n最高分: {result['max_student']} - {result['max_score']:.0f}分")
        lines.append(f"最低分: {result['min_student']} - {result['min_score']:.0f}分")
        lines.append("\n【AI点评】")
        lines.append(self._generate_class_comment(result))

        return "\n".join(lines)

    def _format_grade_eval(self, result: Dict) -> str:
        gn = GRADE_NAMES.get(result['grade_code'], result['grade_code'])
        lines = [
            f"【{gn} 年级整体分析】",
            f"总人数: {result['total_students']} | 班级数: {result['class_count']}",
            f"年级均分: {result['grade_avg']}",
            "-------- 各班级对比 --------"
        ]
        for cls in sorted(result['classes'], key=lambda c: c['class_avg'], reverse=True):
            level = self.evaluator.get_grade_level(cls['class_avg'])
            lines.append(f"  {cls['grade']}: {cls['class_avg']}分 ({cls['student_count']}人) {level}")

        lines.append("\n【AI点评】")
        lines.append(self._generate_grade_comment(result))
        return "\n".join(lines)

    def _format_stats(self) -> str:
        total = self.db.fetchone("SELECT COUNT(*) as cnt FROM students")
        count = total["cnt"] if total else 0
        if count == 0:
            return "系统中暂无学生数据"

        stats = self.db.fetchone("SELECT AVG(total_score) as avg, MIN(total_score) as min_s, MAX(total_score) as max_s FROM students")
        pass_count = self.db.fetchone("SELECT COUNT(*) as cnt FROM students WHERE total_score >= 360")
        top = self.db.fetchone("SELECT * FROM students ORDER BY total_score DESC LIMIT 1")

        grade_dist = self.db.fetchall("SELECT grade_code, COUNT(*) as cnt FROM students GROUP BY grade_code")
        grade_info = ""
        for gd in grade_dist:
            gn = GRADE_NAMES.get(gd["grade_code"], gd["grade_code"])
            grade_info += f"\n  {gn}: {gd['cnt']}人"

        top_info = ""
        if top:
            top_info = f"\n第一名: {top['name']} ({top['student_id']}) 总分: {top['total_score']:.0f}"

        return (
            f"【系统数据概览】\n"
            f"学生总数: {count} 人{grade_info}\n"
            f"平均总分: {stats['avg']:.1f}\n"
            f"总分范围: {stats['min_s']:.0f} - {stats['max_s']:.0f}\n"
            f"及格率(>=360分): {pass_count['cnt']/count*100:.0f}%"
            f"{top_info}"
        )

    def _generate_class_comment(self, result: Dict) -> str:
        avg = result['class_avg']
        pass_pct = result['pass_count'] / result['student_count'] * 100

        parts = []
        if avg >= 85:
            parts.append(f"{result['grade']}整体表现非常出色！班级均分{avg}分。")
        elif avg >= 75:
            parts.append(f"{result['grade']}表现良好，均分{avg}分，及格率{pass_pct:.0f}%。")
        elif avg >= 65:
            parts.append(f"{result['grade']}处于中等水平，均分{avg}分。")
        else:
            parts.append(f"{result['grade']}成绩偏低（均分{avg}分）。")

        best_subj = max(result['subject_averages'], key=result['subject_averages'].get)
        worst_subj = min(result['subject_averages'], key=result['subject_averages'].get)
        parts.append(f"最强科目是「{best_subj}」（{result['subject_averages'][best_subj]}分），需加强的是「{worst_subj}」（{result['subject_averages'][worst_subj]}分）。")

        good = result['level_distribution'].get("优秀", 0) + result['level_distribution'].get("良好", 0)
        fail = result['level_distribution'].get("不及格", 0)
        if good > fail:
            parts.append(f"班级整体向好，优秀和良好{good}人，不及格{fail}人。")
        elif fail > good:
            parts.append(f"需重点关注不及格的{fail}位同学。")

        parts.append(random.choice([
            "继续加油，未来可期！", "一分耕耘一分收获，继续努力！",
            "保持势头，争取更大进步！", "学习是场马拉松，坚持就是胜利！"
        ]))
        return "\n".join(parts)

    def _generate_grade_comment(self, result: Dict) -> str:
        classes = sorted(result['classes'], key=lambda c: c['class_avg'], reverse=True)
        best = classes[0] if classes else None
        worst = classes[-1] if classes else None
        gn = GRADE_NAMES.get(result['grade_code'], result['grade_code'])

        parts = [f"{gn}共有{result['total_students']}位同学分布在{result['class_count']}个班级中。"]
        if best and worst:
            diff = best['class_avg'] - worst['class_avg']
            if diff > 15:
                parts.append(f"各班差距较大：最好的是{best['grade']}（均分{best['class_avg']}），需加油的是{worst['grade']}（均分{worst['class_avg']}）。建议加强班际交流。")
            else:
                parts.append(f"各班发展较均衡：{best['grade']}最好（均分{best['class_avg']}），{worst['grade']}需加油（均分{worst['class_avg']}）。")

        parts.append(random.choice([
            "各班级之间多交流学习经验，共同进步！",
            "整体态势良好，继续努力！",
            "希望各班级齐头并进，共创佳绩！"
        ]))
        return "\n".join(parts)

    def _generate_ai_comment(self, func: str, params: Any, original_text: str):
        try:
            if func == "evaluate_class" and params:
                gy, cn = params
                gn = GRADE_NAMES.get(gy, gy)
                result = self.evaluator.evaluate_class(self.db, gy, cn)
                if result:
                    prompt = f"我已查看了{gn}{cn}班的成绩数据（均分{result['class_avg']}，{result['student_count']}人）。请给我一段简短温暖的点评（50字以内），鼓励这个班级。"
            elif func == "evaluate_grade" and params:
                gy = params
                result = self.evaluator.evaluate_grade(self.db, gy)
                if result:
                    prompt = f"我已分析了{GRADE_NAMES.get(gy, gy)}的整体成绩（{result['total_students']}人，{result['class_count']}个班）。请给我一段简短温暖的鼓励（50字以内）。"
            elif func == "evaluate_student" and params:
                _, value = params
                prompt = f"请给学生「{value}」一句简短的学习鼓励（20字以内）。"
            elif func == "rank_total":
                prompt = "请用一句话鼓励全校学生继续努力（20字以内）。"
            elif func == "stats":
                prompt = "请用一句话总结成绩管理系统的作用（20字以内）。"
            else:
                return

            if self.ai_engine.deepseek.available:
                messages = [
                    {"role": "system", "content": "你是一个温暖的AI教育助手，用简短、鼓励的话语回复。"},
                    {"role": "user", "content": prompt}
                ]
                worker = AIWorker(self.ai_engine.deepseek, messages, temperature=0.9)
                self._ai_workers.append(worker)
                worker.finished.connect(lambda resp, w=worker: self._on_ai_comment_finished(resp, w))
                worker.error.connect(lambda err, w=worker: self._on_ai_comment_error(err, w))
                worker.start()
        except Exception as e:
            print(f"[AI Comment] Error: {e}")

    def _on_ai_comment_finished(self, response: str, worker: AIWorker):
        if response and len(response) > 5:
            try:
                self._append_message("system", f"[AI] {response}")
            except:
                pass
        self._remove_ai_worker(worker)

    def _on_ai_comment_error(self, error_msg: str, worker: AIWorker):
        self._remove_ai_worker(worker)

    def _remove_ai_worker(self, worker: AIWorker):
        try:
            worker.safe_stop()
            worker.quit()
            worker.wait(1000)
            if worker in self._ai_workers:
                self._ai_workers.remove(worker)
        except:
            pass

    # ========== 按钮功能 ==========

    def show_all(self):
        self.input_box.setText("显示所有学生")
        self.send_message()

    def show_rank_total(self):
        self.input_box.setText("总分排名")
        self.send_message()

    def show_rank_class(self):
        try:
            dialog = RankSelectDialog(self.db, 'class', self)
            if dialog.exec_() == QDialog.Accepted and dialog.result_params:
                gy, cn = dialog.result_params
                gn = GRADE_NAMES.get(gy, gy)
                self.input_box.setText(f"{gn}{cn}班排名")
                self.send_message()
            return
        except Exception as e:
            print(f"[RankSelectDialog.class] Error: {e}")
            self.input_box.setText("班级排名")
            self.send_message()

    def show_rank_grade(self):
        try:
            dialog = RankSelectDialog(self.db, 'grade', self)
            if dialog.exec_() == QDialog.Accepted and dialog.result_params:
                gy = dialog.result_params
                gn = GRADE_NAMES.get(gy, gy)
                self.input_box.setText(f"{gn}年级排名")
                self.send_message()
            return
        except Exception as e:
            print(f"[RankSelectDialog.grade] Error: {e}")
            self.input_box.setText("年级排名")
            self.send_message()

    def show_menu(self):
        self.input_box.setText("菜单")
        self.send_message()

    def _show_rank_subject(self):
        try:
            dialog = RankSelectDialog(self.db, 'subject', self)
            if dialog.exec_() == QDialog.Accepted and dialog.result_params:
                subject = dialog.result_params
                self.input_box.setText(f"{subject}排名")
                self.send_message()
            return
        except Exception as e:
            print(f"[RankSelectDialog.subject] Error: {e}")
            self.input_box.setText("总分排名")
            self.send_message()

    def export_excel(self):
        try:
            from openpyxl import Workbook
            file_path, _ = QFileDialog.getSaveFileName(
                self, "导出Excel", "学生成绩管理系统.xlsx", "Excel文件 (*.xlsx)"
            )
            if not file_path:
                return

            wb = Workbook()
            ws = wb.active
            ws.title = "学生成绩"

            headers = ["学号", "姓名", "性别", "年级", "班级", "语文", "数学", "英语", "物理", "化学", "生物", "总分"]
            ws.append(headers)

            students = self.db.fetchall("SELECT * FROM students ORDER BY grade_code, class_code, student_id")
            for s in students:
                ws.append([
                    s["student_id"], s["name"], s["gender"],
                    GRADE_NAMES.get(s["grade_code"], s["grade_code"]),
                    f"{s['class_code']}班",
                    s["chinese"], s["math"], s["english"],
                    s["physics"], s["chemistry"], s["biology"],
                    s["total_score"]
                ])

            wb.save(file_path)
            QMessageBox.information(self, "成功", f"已导出 {len(students)} 条数据到\n{file_path}")
            self._append_message("system", f"已导出 {len(students)} 条数据到 Excel 文件")
        except ImportError:
            QMessageBox.warning(self, "导出失败", "请先安装 openpyxl:\n  pip install openpyxl")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def open_table_dialog(self):
        try:
            dialog = DataTableDialog(self.db, self)
            dialog.exec_()
            self._refresh_table()
            self._update_grade_filter()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开表格视图时出错: {e}")

    def closeEvent(self, event):
        try:
            self.db.close()
        except:
            pass
        event.accept()


class DataTableDialog(QDialog):
    """数据表格编辑对话框"""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("学生成绩数据表 - 编辑视图")
        self.resize(1100, 650)
        self.setStyleSheet("""
            QDialog { background: #f5f7fa; }
            QTableWidget { background: white; border: 1px solid #ddd; border-radius: 6px; gridline-color: #eee; font-size: 13px; }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:selected { background: #667eea; color: white; }
            QHeaderView::section { background: #667eea; color: white; padding: 8px; border: none; font-weight: bold; }
            QPushButton { padding: 8px 16px; border: none; border-radius: 4px; background: #667eea; color: white; }
            QPushButton:hover { background: #5a6fd6; }
        """)
        self._setup_ui()
        self.load_data()

    def _setup_ui(self):
        layout = QVBoxLayout()

        toolbar = QHBoxLayout()
        self.grade_filter = QComboBox()
        self.grade_filter.addItem("全部年级")
        try:
            grades = self.db.get_available_grades()
            for g in grades:
                self.grade_filter.addItem(f"{GRADE_NAMES.get(g, g)}({g})")
        except:
            pass
        self.grade_filter.currentIndexChanged.connect(self.load_data)
        toolbar.addWidget(QLabel("年级:"))
        toolbar.addWidget(self.grade_filter)

        self.class_filter = QComboBox()
        self.class_filter.addItem("全部班级")
        self._update_class_filter()
        self.class_filter.currentIndexChanged.connect(self.load_data)
        toolbar.addWidget(QLabel("班级:"))
        toolbar.addWidget(self.class_filter)
        toolbar.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_data)
        toolbar.addWidget(refresh_btn)

        save_btn = QPushButton("保存修改")
        save_btn.clicked.connect(self.save_changes)
        toolbar.addWidget(save_btn)

        export_btn = QPushButton("导出Excel")
        export_btn.clicked.connect(self.export_excel)
        toolbar.addWidget(export_btn)

        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels(
            ["学号", "姓名", "性别", "年级", "班级", "语文", "数学", "英语", "物理", "化学", "生物", "总分"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("padding: 8px; background: white; border: 1px solid #ddd; border-radius: 4px; font-size: 13px;")
        layout.addWidget(self.stats_label)

        self.setLayout(layout)

    def _update_class_filter(self):
        try:
            classes = self.db.get_available_classes()
            for c in classes:
                self.class_filter.addItem(f"{c}班")
        except:
            pass

    def load_data(self):
        try:
            self.table.itemChanged.disconnect()
        except:
            pass

        self.table.setSortingEnabled(False)

        grade_text = self.grade_filter.currentText()
        class_text = self.class_filter.currentText()

        sql = "SELECT * FROM students"
        conditions = []

        for gname, gcode in GRADE_CODES.items():
            if gname in grade_text and "全部" not in grade_text:
                conditions.append(f"grade_code='{gcode}'")
                break

        if class_text != "全部班级":
            class_code = class_text[:2]
            conditions.append(f"class_code='{class_code}'")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY grade_code, class_code, student_id"

        students = self.db.fetchall(sql)
        self.students_data = [dict(s) for s in students]

        self.table.setRowCount(len(students))

        for row, s in enumerate(students):
            gn = GRADE_NAMES.get(s["grade_code"], s["grade_code"])
            items = [
                s["student_id"], s["name"], s["gender"],
                gn, f"{s['class_code']}班",
                str(int(s["chinese"])), str(int(s["math"])),
                str(int(s["english"])), str(int(s["physics"])),
                str(int(s["chemistry"])), str(int(s["biology"])),
                str(int(s["total_score"]))
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if 5 <= col <= 10:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setBackground(QColor(240, 255, 240))
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

        if students:
            totals = [s["total_score"] for s in students]
            avg = sum(totals) / len(totals)
            self.stats_label.setText(
                f"共 {len(students)} 名学生 | 总分范围: {min(totals):.0f} - {max(totals):.0f} | 平均分: {avg:.1f}"
            )
        else:
            self.stats_label.setText("暂无数据")

        self.modified_cells = {}
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self.on_item_changed)

    def on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if 5 <= col <= 10:
            try:
                val = float(item.text())
                if val < 0 or val > 100:
                    QMessageBox.warning(self, "无效输入", "成绩必须在0-100之间")
                    self.load_data()
                    return

                scores = []
                for c in range(5, 11):
                    cell = self.table.item(row, c)
                    scores.append(float(cell.text()) if cell else 0)

                total = sum(scores)
                total_item = self.table.item(row, 11)
                if total_item:
                    total_item.setText(str(int(total)))

                student_id_item = self.table.item(row, 0)
                if student_id_item:
                    self.modified_cells[student_id_item.text()] = scores

            except ValueError:
                pass

    def save_changes(self):
        if not self.modified_cells:
            QMessageBox.information(self, "提示", "没有需要保存的修改")
            return

        try:
            count = 0
            for sid, scores in self.modified_cells.items():
                self.db.execute(
                    "UPDATE students SET chinese=?, math=?, english=?, physics=?, chemistry=?, biology=?, total_score=? WHERE student_id=?",
                    (scores[0], scores[1], scores[2], scores[3], scores[4], scores[5], sum(scores), sid)
                )
                count += 1

            self.db.update_all_ranks()
            self.modified_cells = {}
            QMessageBox.information(self, "成功", f"已保存 {count} 名学生的修改，并更新了排名")
            self.load_data()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def export_excel(self):
        try:
            from openpyxl import Workbook
            file_path, _ = QFileDialog.getSaveFileName(
                self, "导出Excel", "学生成绩管理系统.xlsx", "Excel文件 (*.xlsx)"
            )
            if not file_path:
                return

            wb = Workbook()
            ws = wb.active
            ws.title = "学生成绩"
            headers = ["学号", "姓名", "性别", "年级", "班级", "语文", "数学", "英语", "物理", "化学", "生物", "总分"]
            ws.append(headers)

            students = self.db.fetchall("SELECT * FROM students ORDER BY grade_code, class_code, student_id")
            for s in students:
                ws.append([
                    s["student_id"], s["name"], s["gender"],
                    GRADE_NAMES.get(s["grade_code"], s["grade_code"]),
                    f"{s['class_code']}班",
                    s["chinese"], s["math"], s["english"],
                    s["physics"], s["chemistry"], s["biology"],
                    s["total_score"]
                ])

            wb.save(file_path)
            QMessageBox.information(self, "成功", f"已导出 {len(students)} 条数据到\n{file_path}")
        except ImportError:
            QMessageBox.warning(self, "导出失败", "请先安装 openpyxl: pip install openpyxl")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


class RankSelectDialog(QDialog):
    """排名选择对话框"""

    def __init__(self, db: Database, rank_type: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.rank_type = rank_type
        self.result_params = None
        self.setWindowTitle("选择排名范围")
        self.setFixedSize(400, 280)
        self.setStyleSheet("""
            QDialog { background: white; border-radius: 10px; }
            QLabel { font-size: 15px; padding: 6px; color: #333; }
            QComboBox { padding: 8px 12px; font-size: 14px; border: 2px solid #e0e0e0; border-radius: 6px; background: white; min-height: 22px; }
            QComboBox:hover { border-color: #667eea; }
            QComboBox:focus { border-color: #667eea; }
            QComboBox::drop-down { border: none; width: 30px; }
            QPushButton { padding: 10px 28px; font-size: 14px; font-weight: bold; border: none; border-radius: 6px; min-height: 20px; }
            QPushButton:hover { background: #5a6fd6; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(14)
        layout.setContentsMargins(30, 24, 30, 24)

        type_names = {'class': '班级排名', 'grade': '年级排名', 'subject': '单科排名'}
        title = QLabel(f"[排名] {type_names.get(self.rank_type, '排名')}")
        title.setFont(get_font(18, True))
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #667eea; padding: 4px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(QLabel("选择年级:"))
        self.grade_combo = QComboBox()
        try:
            grades = self.db.get_available_grades()
            for g in grades:
                self.grade_combo.addItem(f"{GRADE_NAMES.get(g, g)}({g})", g)
        except:
            self.grade_combo.addItem("高一", "01")
            self.grade_combo.addItem("高二", "02")
            self.grade_combo.addItem("高三", "03")
        self.grade_combo.setFont(get_font(14))
        layout.addWidget(self.grade_combo)

        self.class_combo = None
        if self.rank_type == 'class':
            self.class_label = QLabel("选择班级:")
            layout.addWidget(self.class_label)
            self.class_combo = QComboBox()
            self.class_combo.setFont(get_font(14))
            self._update_class_list()
            self.grade_combo.currentIndexChanged.connect(self._update_class_list)
            layout.addWidget(self.class_combo)

        self.subject_combo = None
        if self.rank_type == 'subject':
            self.subject_label = QLabel("选择科目:")
            layout.addWidget(self.subject_label)
            self.subject_combo = QComboBox()
            self.subject_combo.setFont(get_font(14))
            for subj in SUBJECTS:
                self.subject_combo.addItem(subj)
            layout.addWidget(self.subject_combo)

        layout.addSpacing(12)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("查看排名")
        ok_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #667eea, stop:1 #764ba2); color: white; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6fd6, stop:1 #6a41a2); }"
        )
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #95a5a6; color: white; } QPushButton:hover { background: #7f8c8d; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _update_class_list(self):
        try:
            self.class_combo.blockSignals(True)
            self.class_combo.clear()
            grade_code = self.grade_combo.currentData()
            classes = self.db.get_available_classes(grade_code)
            for c in classes:
                self.class_combo.addItem(f"{c}班", c)
            self.class_combo.blockSignals(False)
        except:
            pass

    def _on_ok(self):
        grade_code = self.grade_combo.currentData()

        if self.rank_type == 'class':
            if not self.class_combo:
                self.reject()
                return
            class_code = self.class_combo.currentData()
            if not class_code:
                QMessageBox.warning(self, "提示", "请选择班级")
                return
            self.result_params = (grade_code, class_code)

        elif self.rank_type == 'grade':
            self.result_params = grade_code

        elif self.rank_type == 'subject':
            subject = self.subject_combo.currentText()
            self.result_params = subject

        self.accept()


class AddStudentDialog(QDialog):
    """添加学生对话框"""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.student_id = None
        self.setWindowTitle("添加新学生")
        self.setFixedSize(420, 380)
        self.setStyleSheet("""
            QDialog { background: white; }
            QLabel { font-size: 14px; padding: 4px; }
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ddd; border-radius: 4px; }
            QLineEdit:focus { border-color: #667eea; }
            QComboBox { padding: 6px; font-size: 14px; border: 1px solid #ddd; border-radius: 4px; }
            QPushButton { padding: 10px 20px; font-size: 14px; border: none; border-radius: 4px; background: #667eea; color: white; }
            QPushButton:hover { background: #5a6fd6; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        form = QFormLayout()

        self.sid_input = QLineEdit()
        self.sid_input.setPlaceholderText("8位学号，如: 01010099")
        form.addRow("学号:", self.sid_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("学生姓名")
        form.addRow("姓名:", self.name_input)

        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["男", "女"])
        form.addRow("性别:", self.gender_combo)

        self.score_inputs = []
        for subj in SUBJECTS:
            inp = QLineEdit()
            inp.setPlaceholderText("0-100")
            self.score_inputs.append(inp)
            form.addRow(f"{subj}:", inp)

        layout.addLayout(form)

        btns = QHBoxLayout()
        ok_btn = QPushButton("确定添加")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("QPushButton { background: #95a5a6; } QPushButton:hover { background: #7f8c8d; }")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.setLayout(layout)

    def _on_ok(self):
        sid = self.sid_input.text().strip()
        name = self.name_input.text().strip()
        gender = self.gender_combo.currentText()

        if not sid or not name:
            QMessageBox.warning(self, "错误", "学号和姓名不能为空")
            return

        # 校验学号
        valid, info = StudentIDValidator.parse(sid)
        if not valid:
            QMessageBox.warning(self, "学号格式错误", info)
            return

        # 检查重复
        exist = self.db.fetchone("SELECT student_id FROM students WHERE student_id=?", (sid,))
        if exist:
            QMessageBox.warning(self, "错误", f"学号 {sid} 已存在！")
            return

        # 解析成绩
        scores = []
        for inp in self.score_inputs:
            try:
                s = float(inp.text()) if inp.text().strip() else 0
                if s < 0 or s > 100:
                    QMessageBox.warning(self, "错误", "成绩必须在0-100之间")
                    return
                scores.append(s)
            except ValueError:
                QMessageBox.warning(self, "错误", "请输入有效的成绩数字")
                return

        total = sum(scores)

        try:
            self.db.execute("""
                INSERT INTO students 
                (student_id, name, gender, grade_code, class_code,
                 chinese, math, english, physics, chemistry, biology, total_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sid, name, gender, info["grade_code"], info["class_code"],
                  scores[0], scores[1], scores[2], scores[3], scores[4], scores[5], total))

            self.db.update_all_ranks()
            self.student_id = sid
            self.accept()

        except Exception as e:
            QMessageBox.warning(self, "错误", f"添加失败: {e}")


# ===================== 主入口 =====================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font = QFont("Microsoft YaHei", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    login = LoginDialog()
    if login.exec_() != QDialog.Accepted:
        return

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
