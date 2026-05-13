import sys
import re
import os
import sqlite3
import hashlib
import threading
import json
import requests
from openpyxl import Workbook
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

# ===================== 火山方舟配置 =====================
ARK_API_KEY = "ark-30711e25-3b33-4893-81ea-3807b4613a59-6a7b3"
EP_ID = "ep-20260513194638-8qdxg"
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

DB_NAME = "school_final.db"
EXCEL_PATH = os.path.join(os.getcwd(), "学生成绩管理系统.xlsx")

# ===================== 学号标准 =====================
# 学号格式：GGCCNNNN（8位数字）
# GG = 年级代码：01=高一, 02=高二, 03=高三
# CC = 班级编号：01~30
# NNNN = 顺序号：0001~9999
#
# 示例：01010001 = 高一1班第1号学生
#       02020015 = 高二2班第15号学生

GRADE_MAP = {"01": "高一", "02": "高二", "03": "高三"}
GRADE_REVERSE_MAP = {"高一": "01", "高二": "02", "高三": "03"}

def validate_student_id(sid):
    """验证学号格式，返回 (是否合法, 错误信息, 年级, 班级)"""
    if not sid or not isinstance(sid, str):
        return False, "学号不能为空", "", ""
    
    # 检查是否为纯数字
    if not sid.isdigit():
        return False, "学号必须为纯数字", "", ""
    
    # 检查长度
    if len(sid) != 8:
        return False, "学号必须为8位数字（格式：GGCCNNNN，如01010001）", "", ""
    
    grade_code = sid[:2]
    class_code = sid[2:4]
    seq_num = sid[4:]
    
    # 检查年级代码
    if grade_code not in GRADE_MAP:
        return False, f"年级代码错误：{grade_code}，应为01(高一)、02(高二)、03(高三)", "", ""
    
    # 检查班级编号
    class_num = int(class_code)
    if class_num < 1 or class_num > 30:
        return False, f"班级编号错误：{class_code}，范围应为01~30", "", ""
    
    # 检查顺序号
    seq_num_int = int(seq_num)
    if seq_num_int < 1 or seq_num_int > 9999:
        return False, f"顺序号错误：{seq_num}，范围应为0001~9999", "", ""
    
    grade = GRADE_MAP[grade_code]
    class_full = f"{grade}{int(class_code)}班"
    
    return True, "", grade, class_full


# ===================== 火山方舟豆包AI =====================
class DoubaoAI:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {ARK_API_KEY}",
            "Content-Type": "application/json"
        }
        self.last_input = ""
        self.last_response = ""

    def call_api(self, messages, temperature=0.7, max_tokens=1024):
        """调用火山方舟API"""
        payload = {
            "model": EP_ID,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        try:
            resp = requests.post(ARK_URL, headers=self.headers, json=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                return None
        except Exception as e:
            return None

    def preprocess_input(self, text):
        if not text:
            return ""
        
        text = text.strip()
        text = re.sub(r'[\s\u3000\u00A0]+', ' ', text)
        text = re.sub(r'[，。！？、；：""()（）【】《》]', '', text)
        text = re.sub(r'[^\w\u4e00-\u9fa5|\s]', '', text)
        text = text.strip()
        
        return text

    def parse_intent(self, user_text):
        """解析用户意图，返回标准指令或 'unknown' 或分析类指令"""
        text = self.preprocess_input(user_text)
        if not text:
            return "unknown"

        # 固定指令：修改/更新成绩
        if text.startswith("update|") or text.startswith("修改|"):
            parts = text.split("|")
            if len(parts) >= 4:
                name = parts[1] if parts[0].startswith("update") else parts[1]
                subject = parts[2] if parts[0].startswith("update") else parts[2]
                score = parts[3] if parts[0].startswith("update") else parts[3]
                return f"update|{name}|{subject}|{score}"
            return "unknown"

        # 固定指令：删除
        if text.startswith("delete|") or text.startswith("删除|"):
            parts = text.split("|")
            name = parts[1] if len(parts) >= 2 else ""
            return f"delete|{name}"

        # 固定指令：导出
        if "导出" in text and ("excel" in text.lower() or "表格" in text or "文件" in text):
            return "export_excel"

        # ===== 分析类指令 =====
        # 分析xx班成绩 / 分析xx年级成绩 / 分析某科成绩
        analyze_patterns = [
            r"分析(.{2,20})班(?:的)?(?:成绩)?",
            r"分析(.{2,20})年级(?:的)?(?:成绩)?",
            r"(.{2,20})班(?:的)?成绩(?:怎么|如何|分析)?",
            r"(.{2,20})年级(?:的)?成绩(?:怎么|如何|分析)?",
            r"看看(.{2,20})班(?:的)?(?:成绩)?",
            r"看看(.{2,20})年级(?:的)?(?:成绩)?",
            r"成绩分析(.{2,20})?",
            r"分析(?:一下)?(.{2,10})(?:的)?(语文|数学|英语|物理)?(?:成绩)?",
        ]
        for pattern in analyze_patterns:
            m = re.search(pattern, text)
            if m:
                target = m.group(1).strip() if m.lastindex >= 1 else ""
                subject = m.group(2).strip() if m.lastindex >= 2 else ""
                return f"analyze|{target}|{subject}"

        # 固定指令：显示所有学生
        if "显示" in text and "学生" in text:
            return "show_all"
        if "所有" in text and "学生" in text:
            return "show_all"
        if "全部" in text and "学生" in text:
            return "show_all"
        if "学生" in text and ("列表" in text or "名单" in text):
            return "show_all"

        # 固定指令：排名
        if "排名" in text or "排行" in text:
            # 班级排名
            class_rank_match = re.search(r"(\d+)班(?:的)?(.{0,4})排名", text)
            if class_rank_match:
                class_num = class_rank_match.group(1)
                subj = class_rank_match.group(2).strip()
                return f"class_rank|{class_num}班|{subj}"

            # 年级排名
            grade_rank_match = re.search(r"(高一|高二|高三)(?:的)?(.{0,4})排名", text)
            if grade_rank_match:
                grade_str = grade_rank_match.group(1)
                subj = grade_rank_match.group(2).strip()
                return f"grade_rank|{grade_str}|{subj}"

            if "总分" in text or "总排" in text:
                return "rank_total"
            if "语文" in text:
                return "rank_chinese"
            if "数学" in text:
                return "rank_math"
            if "英语" in text:
                return "rank_english"
            if "物理" in text:
                return "rank_physics"
            if "班级" in text:
                return "rank_total"
            return "rank_total"

        # 固定指令：修改成绩（自然语言解析）
        m = re.search(r"(?:修改|更改|更新)?\s*([^的]+?)的?([语文数学英语物理]+)成绩(?:为|到|成|是)?(\d{1,3})", text)
        if m:
            name = m.group(1).strip()
            subject = m.group(2).strip()
            score = m.group(3)
            return f"update|{name}|{subject}|{score}"

        # 固定指令：删除学生
        m = re.search(r"删除\s*([^\s]+)", text)
        if m:
            name = m.group(1).strip()
            return f"delete|{name}"

        # 固定指令：添加学生
        add_match = re.search(r"添加学生\s*(\S+)\s*(\S+)\s*(\S+)\s*(\S+)", text)
        if add_match:
            sid = add_match.group(1)
            name = add_match.group(2)
            gender = add_match.group(3)
            yw = add_match.group(4)
            return f"add_student|{sid}|{name}|{gender}|{yw}"

        # 默认规则兜底
        if "显示" in text or "查看" in text:
            return "show_all"

        return "unknown"


# ===================== 数据库（完整功能 + 20名学生初始化） =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.cur = self.conn.cursor()
        self.init_tables()
        self.init_20_students()

    def init_tables(self):
        # 重新建表：添加 grade 字段
        self.cur.execute('''CREATE TABLE IF NOT EXISTS student (
            sid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            gender TEXT,
            grade TEXT,
            class TEXT
        )''')
        self.cur.execute('''CREATE TABLE IF NOT EXISTS score (
            sid TEXT PRIMARY KEY,
            语文 REAL DEFAULT 0,
            数学 REAL DEFAULT 0,
            英语 REAL DEFAULT 0,
            物理 REAL DEFAULT 0,
            总分 REAL DEFAULT 0,
            平均分 REAL DEFAULT 0
        )''')
        self.cur.execute('''CREATE TABLE IF NOT EXISTS user (
            username TEXT PRIMARY KEY,
            password TEXT
        )''')
        pwd = hashlib.md5("123456".encode()).hexdigest()
        self.cur.execute("REPLACE INTO user VALUES (?,?)", ("admin", pwd))
        self.conn.commit()

    def init_20_students(self):
        # 检查是否已有数据
        existing = self.cur.execute("SELECT COUNT(*) FROM student").fetchone()[0]
        if existing >= 20:
            return
        
        # 清空旧数据
        self.cur.execute("DELETE FROM student")
        self.cur.execute("DELETE FROM score")
        
        # 分布在不同年级/班级的学生数据
        # 格式: (学号, 姓名, 性别, 年级, 班级全名, 语文, 数学, 英语, 物理)
        students = [
            # === 高一1班（10人）===
            ("01010001", "张三",   "男", "高一", "高一1班", 80, 85, 90, 95),
            ("01010002", "李四",   "女", "高一", "高一1班", 78, 82, 88, 90),
            ("01010003", "王五",   "男", "高一", "高一1班", 92, 76, 85, 80),
            ("01010004", "赵六",   "男", "高一", "高一1班", 65, 95, 70, 75),
            ("01010005", "钱七",   "女", "高一", "高一1班", 85, 60, 92, 88),
            ("01010006", "孙八",   "男", "高一", "高一1班", 70, 78, 80, 82),
            ("01010007", "周九",   "女", "高一", "高一1班", 90, 94, 76, 66),
            ("01010008", "吴十",   "男", "高一", "高一1班", 55, 88, 95, 76),
            ("01010009", "郑十一", "女", "高一", "高一1班", 88, 72, 68, 94),
            ("01010010", "冯十二", "男", "高一", "高一1班", 76, 66, 84, 78),
            # === 高一2班（5人）===
            ("01020001", "陈十三", "女", "高一", "高一2班", 82, 90, 62, 70),
            ("01020002", "褚十四", "男", "高一", "高一2班", 68, 74, 78, 86),
            ("01020003", "卫十五", "女", "高一", "高一2班", 94, 68, 72, 64),
            ("01020004", "蒋十六", "男", "高一", "高一2班", 60, 80, 96, 72),
            ("01020005", "沈十七", "女", "高一", "高一2班", 74, 92, 66, 84),
            # === 高二1班（5人）===
            ("02010001", "韩十八", "男", "高二", "高二1班", 86, 58, 74, 92),
            ("02010002", "杨十九", "女", "高二", "高二1班", 62, 70, 82, 96),
            ("02010003", "朱二十", "男", "高二", "高二1班", 96, 64, 58, 70),
            ("02010004", "秦二十一", "女", "高二", "高二1班", 72, 86, 90, 62),
            ("02010005", "尤二十二", "男", "高二", "高二1班", 64, 98, 64, 58),
        ]
        
        for sid, name, gender, grade, cls, yw, sx, yy, wl in students:
            total = yw + sx + yy + wl
            avg = round(total / 4, 1)
            self.cur.execute("REPLACE INTO student VALUES (?,?,?,?,?)", (sid, name, gender, grade, cls))
            self.cur.execute("REPLACE INTO score VALUES (?,?,?,?,?,?,?)", (sid, yw, sx, yy, wl, total, avg))
        
        self.conn.commit()

    # ==================== 查询方法 ====================
    
    def get_all_table(self):
        data = self.cur.execute('''
            SELECT s.sid,s.name,s.gender,s.grade,s.class,sc.语文,sc.数学,sc.英语,sc.物理,sc.总分,sc.平均分
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            ORDER BY s.sid
        ''').fetchall()
        txt = f"{'学号':<10}{'姓名':<8}{'性别':<5}{'年级':<6}{'班级':<8}{'语文':<6}{'数学':<6}{'英语':<6}{'物理':<6}{'总分':<7}{'平均分'}\n"
        txt += "-" * 110 + "\n"
        for d in data:
            txt += f"{d[0]:<10}{d[1]:<8}{d[2]:<5}{d[3]:<6}{d[4]:<8}{d[5]:<6}{d[6]:<6}{d[7]:<6}{d[8]:<6}{d[9]:<7}{d[10]}\n"
        return txt

    def get_rank(self, field="总分"):
        """全校排名"""
        data = self.cur.execute(f'''
            SELECT s.sid,s.name,s.gender,s.grade,s.class,sc.{field}
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            ORDER BY sc.{field} DESC
        ''').fetchall()
        txt = f"📊 全校{field}排名\n"
        txt += f"{'名次':<5}{'学号':<10}{'姓名':<8}{'性别':<5}{'年级':<6}{'班级':<8}{field:<6}\n"
        txt += "-" * 60 + "\n"
        for i, d in enumerate(data, 1):
            txt += f"{i:<5}{d[0]:<10}{d[1]:<8}{d[2]:<5}{d[3]:<6}{d[4]:<8}{d[5]:<6}\n"
        return txt

    def get_class_rank(self, class_name, field=""):
        """班级排名"""
        if not field:
            field = "总分"
        data = self.cur.execute(f'''
            SELECT s.sid,s.name,s.gender,s.grade,s.class,sc.{field}
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            WHERE s.class=?
            ORDER BY sc.{field} DESC
        ''').fetchall()
        if not data:
            return f"❌ 未找到班级 '{class_name}' 的学生数据"
        
        txt = f"📊 {class_name}{field}排名\n"
        txt += f"{'名次':<5}{'学号':<10}{'姓名':<8}{'性别':<5}{field:<6}\n"
        txt += "-" * 40 + "\n"
        for i, d in enumerate(data, 1):
            txt += f"{i:<5}{d[0]:<10}{d[1]:<8}{d[2]:<5}{d[3]:<6}\n"
        return txt

    def get_grade_rank(self, grade_str, field=""):
        """年级排名"""
        if not field:
            field = "总分"
        data = self.cur.execute(f'''
            SELECT s.sid,s.name,s.gender,s.grade,s.class,sc.{field}
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            WHERE s.grade=?
            ORDER BY sc.{field} DESC
        ''').fetchall()
        if not data:
            return f"❌ 未找到年级 '{grade_str}' 的学生数据"
        
        txt = f"📊 {grade_str}年级{field}排名\n"
        txt += f"{'名次':<5}{'学号':<10}{'姓名':<8}{'性别':<5}{'班级':<8}{field:<6}\n"
        txt += "-" * 50 + "\n"
        for i, d in enumerate(data, 1):
            txt += f"{i:<5}{d[0]:<10}{d[1]:<8}{d[2]:<5}{d[3]:<8}{d[4]:<6}\n"
        return txt

    # ==================== 分析统计方法 ====================
    
    def analyze_class(self, class_name):
        """分析一个班的整体成绩"""
        data = self.cur.execute('''
            SELECT sc.语文, sc.数学, sc.英语, sc.物理, sc.总分
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            WHERE s.class=?
        ''', (class_name,)).fetchall()
        
        if not data:
            return None
        
        subjects = {"语文": [], "数学": [], "英语": [], "物理": [], "总分": []}
        for row in data:
            subjects["语文"].append(row[0])
            subjects["数学"].append(row[1])
            subjects["英语"].append(row[2])
            subjects["物理"].append(row[3])
            subjects["总分"].append(row[4])
        
        student_count = len(data)
        analysis = f"【{class_name}成绩分析】\n"
        analysis += f"📌 班级总人数：{student_count}人\n\n"
        
        for subj, scores in subjects.items():
            if not scores:
                continue
            avg = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            # 计算及格率（>=60）和优秀率（>=90）
            pass_count = sum(1 for s in scores if s >= 60)
            excellent_count = sum(1 for s in scores if s >= 90)
            pass_rate = pass_count / len(scores) * 100
            excellent_rate = excellent_count / len(scores) * 100
            
            analysis += f"▶ {subj}：\n"
            analysis += f"   平均分：{avg:.1f}  最高分：{max_score}  最低分：{min_score}\n"
            analysis += f"   及格率：{pass_rate:.1f}%  优秀率：{excellent_rate:.1f}%\n"
            analysis += "\n"
        
        return analysis
    
    def analyze_grade(self, grade_str):
        """分析一个年级的整体成绩"""
        data = self.cur.execute('''
            SELECT sc.语文, sc.数学, sc.英语, sc.物理, sc.总分, s.class
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            WHERE s.grade=?
        ''', (grade_str,)).fetchall()
        
        if not data:
            return None
        
        subjects = {"语文": [], "数学": [], "英语": [], "物理": [], "总分": []}
        classes = set()
        for row in data:
            subjects["语文"].append(row[0])
            subjects["数学"].append(row[1])
            subjects["英语"].append(row[2])
            subjects["物理"].append(row[3])
            subjects["总分"].append(row[4])
            classes.add(row[5])
        
        student_count = len(data)
        analysis = f"【{grade_str}年级成绩分析】\n"
        analysis += f"📌 年级总人数：{student_count}人，共{len(classes)}个班级\n"
        analysis += f"📌 班级：{'、'.join(sorted(classes))}\n\n"
        
        for subj, scores in subjects.items():
            if not scores:
                continue
            avg = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            pass_count = sum(1 for s in scores if s >= 60)
            excellent_count = sum(1 for s in scores if s >= 90)
            pass_rate = pass_count / len(scores) * 100
            excellent_rate = excellent_count / len(scores) * 100
            
            analysis += f"▶ {subj}：\n"
            analysis += f"   平均分：{avg:.1f}  最高分：{max_score}  最低分：{min_score}\n"
            analysis += f"   及格率：{pass_rate:.1f}%  优秀率：{excellent_rate:.1f}%\n"
            analysis += "\n"
        
        return analysis

    # ==================== 操作方法 ====================

    def add_student(self, sid, name, gender, yw=0, sx=0, yy=0, wl=0):
        """添加学生（带学号验证）"""
        try:
            # 验证学号格式
            valid, err_msg, grade, class_full = validate_student_id(sid)
            if not valid:
                return False, err_msg
            
            # 检查学号是否已存在
            existing = self.cur.execute("SELECT sid FROM student WHERE sid=?", (sid,)).fetchone()
            if existing:
                return False, f"❌ 学号 {sid} 已存在，请检查后重试"
            
            # 添加学生
            self.cur.execute("INSERT INTO student VALUES (?,?,?,?,?)", (sid, name, gender, grade, class_full))
            
            yw = float(yw)
            sx = float(sx)
            yy = float(yy)
            wl = float(wl)
            total = yw + sx + yy + wl
            avg = round(total / 4, 1)
            self.cur.execute("INSERT INTO score VALUES (?,?,?,?,?,?,?)", (sid, yw, sx, yy, wl, total, avg))
            
            self.conn.commit()
            return True, f"✅ 成功添加学生！\n学号：{sid}  姓名：{name}  年级：{grade}  班级：{class_full}"
        except Exception as e:
            return False, f"❌ 添加学生失败：{str(e)}"

    def update_score(self, name, subject, score):
        try:
            score = float(score)
            sid = self.cur.execute("SELECT sid FROM student WHERE name=?", (name,)).fetchone()
            if not sid:
                return False
            sid = sid[0]
            self.cur.execute(f"UPDATE score SET {subject}=? WHERE sid=?", (score, sid))
            r = self.cur.execute("SELECT 语文,数学,英语,物理 FROM score WHERE sid=?", (sid,)).fetchone()
            total = sum(r)
            avg = round(total / 4, 1)
            self.cur.execute("UPDATE score SET 总分=?,平均分=? WHERE sid=?", (total, avg, sid))
            self.conn.commit()
            return True
        except:
            return False

    def delete_student(self, name):
        try:
            # 支持模糊匹配
            sid = self.cur.execute("SELECT sid FROM student WHERE name=?", (name,)).fetchone()
            if not sid:
                # 尝试模糊匹配
                candidates = self.cur.execute("SELECT sid, name FROM student WHERE name LIKE ?", (f"%{name}%",)).fetchall()
                if len(candidates) == 0:
                    return False, "未找到该学生"
                elif len(candidates) > 1:
                    names = [c[1] for c in candidates]
                    return False, f"找到多个匹配学生：{'、'.join(names)}，请使用完整姓名"
                else:
                    sid = candidates[0][0]
            else:
                sid = sid[0]
            
            student_info = self.cur.execute("SELECT name, class FROM student WHERE sid=?", (sid,)).fetchone()
            self.cur.execute("DELETE FROM student WHERE sid=?", (sid,))
            self.cur.execute("DELETE FROM score WHERE sid=?", (sid,))
            self.conn.commit()
            return True, f"✅ 已删除学生：{student_info[0]}（{student_info[1]}）"
        except Exception as e:
            return False, f"❌ 删除失败：{str(e)}"

    def export_excel(self):
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "学生信息"
        ws1.append(["学号", "姓名", "性别", "年级", "班级"])
        for row in self.cur.execute("SELECT * FROM student").fetchall():
            ws1.append(row)
        ws2 = wb.create_sheet("成绩信息")
        ws2.append(["学号", "语文", "数学", "英语", "物理", "总分", "平均分"])
        for row in self.cur.execute("SELECT * FROM score").fetchall():
            ws2.append(row)
        wb.save(EXCEL_PATH)
        return True


# ===================== AI 工作线程 =====================
class AIWorker(QRunnable):
    class Signals(QObject):
        done = pyqtSignal(str)
        error = pyqtSignal(str)

    def __init__(self, ai, db, text):
        super().__init__()
        self.ai = ai
        self.db = db
        self.text = text
        self.signals = self.Signals()

    def run(self):
        try:
            cmd = self.ai.parse_intent(self.text)
            res = ""
            ai_comment = ""
            
            if cmd == "show_all":
                res = self.db.get_all_table()
                ai_comment = self._generate_comment("显示所有学生成绩", res)
                
            elif cmd == "rank_total":
                res = self.db.get_rank("总分")
                ai_comment = self._generate_comment("全校总分排名", res)
                
            elif cmd == "rank_chinese":
                res = self.db.get_rank("语文")
                ai_comment = self._generate_comment("全校语文排名", res)
                
            elif cmd == "rank_math":
                res = self.db.get_rank("数学")
                ai_comment = self._generate_comment("全校数学排名", res)
                
            elif cmd == "rank_english":
                res = self.db.get_rank("英语")
                ai_comment = self._generate_comment("全校英语排名", res)
                
            elif cmd == "rank_physics":
                res = self.db.get_rank("物理")
                ai_comment = self._generate_comment("全校物理排名", res)
                
            elif cmd.startswith("class_rank|"):
                parts = cmd.split("|")
                class_name = parts[1] if len(parts) > 1 else ""
                field = parts[2] if len(parts) > 2 else "总分"
                if field and field not in ["总分", "语文", "数学", "英语", "物理"]:
                    field = "总分"
                res = self.db.get_class_rank(class_name, field)
                ai_comment = self._generate_comment(f"{class_name}班级{field}排名", res)
                
            elif cmd.startswith("grade_rank|"):
                parts = cmd.split("|")
                grade_str = parts[1] if len(parts) > 1 else ""
                field = parts[2] if len(parts) > 2 else "总分"
                if field and field not in ["总分", "语文", "数学", "英语", "物理"]:
                    field = "总分"
                res = self.db.get_grade_rank(grade_str, field)
                ai_comment = self._generate_comment(f"{grade_str}年级{field}排名", res)
                
            elif cmd.startswith("analyze|"):
                parts = cmd.split("|")
                target = parts[1] if len(parts) > 1 else ""
                subject = parts[2] if len(parts) > 2 else ""
                res = self._handle_analyze(target, subject)
                
            elif cmd == "export_excel":
                ok = self.db.export_excel()
                res = "✅ Excel 已导出到当前目录" if ok else "❌ 导出失败"
                ai_comment = self._generate_comment("导出Excel", res)
                
            elif cmd.startswith("update|"):
                parts = cmd.split("|")
                if len(parts) == 4:
                    _, name, subj, score = parts
                    ok = self.db.update_score(name, subj, score)
                    if ok:
                        res = f"✅ 已修改{name}的{subj}成绩为{score}分"
                        ai_comment = self._generate_comment(f"修改{name}的{subj}成绩", res)
                    else:
                        res = "❌ 修改失败，请检查学生姓名和科目是否正确"
                        ai_comment = ""
                else:
                    res = "❌ 指令格式错误，应为：修改|姓名|科目|分数"
                    
            elif cmd.startswith("delete|"):
                parts = cmd.split("|")
                if len(parts) == 2:
                    _, name = parts
                    ok, msg = self.db.delete_student(name)
                    if ok:
                        res = msg
                        ai_comment = self._generate_comment(f"删除学生{name}", res)
                    else:
                        res = msg
                        ai_comment = ""
                else:
                    res = "❌ 指令格式错误，应为：删除|姓名"
                    
            elif cmd.startswith("add_student|"):
                parts = cmd.split("|")
                if len(parts) >= 5:
                    _, sid, name, gender, yw = parts
                    sx = parts[5] if len(parts) > 5 else "0"
                    yy = parts[6] if len(parts) > 6 else "0"
                    wl = parts[7] if len(parts) > 7 else "0"
                    ok, msg = self.db.add_student(sid, name, gender, yw, sx, yy, wl)
                    res = msg
                    if ok:
                        ai_comment = self._generate_comment("添加学生", res)
                else:
                    res = "❌ 指令格式错误，添加学生格式：添加学生 学号 姓名 性别 语文成绩"
                    
            else:
                # 无法匹配固定指令 → 调用AI进行智能回答
                res = self._handle_free_chat(self.text)
            
            # 如果有AI点评，追加到结果后面
            if ai_comment:
                final_res = res + "\n\n" + ai_comment
            else:
                final_res = res
            
            self.signals.done.emit(final_res)
            
        except Exception as e:
            error_msg = f"❌ 处理请求时出错：{str(e)}"
            self.signals.error.emit(error_msg)

    def _handle_analyze(self, target, subject):
        """处理分析类指令"""
        # 尝试匹配年级分析
        if target in ["高一", "高二", "高三"]:
            result = self.db.analyze_grade(target)
            if result:
                return result
            return f"❌ 未找到{target}年级的数据"
        
        # 尝试匹配班级分析（如"高一1班"、"1班"）
        class_candidates = []
        
        # 完整班级名
        if "班" in target:
            full_name = target if (target.startswith("高一") or target.startswith("高二") or target.startswith("高三")) else None
            if full_name:
                class_candidates.append(full_name)
            else:
                # 可能是"1班"
                m = re.match(r"(\d+)班", target)
                if m:
                    num = m.group(1)
                    for g in ["高一", "高二", "高三"]:
                        class_candidates.append(f"{g}{num}班")
        else:
            # 没有"班"字，尝试各种组合
            for g in ["高一", "高二", "高三"]:
                class_candidates.append(f"{g}{target}班")
                class_candidates.append(f"{g}{target}")
        
        for cc in class_candidates:
            result = self.db.analyze_class(cc)
            if result:
                # 如果指定了科目，添加该科目的详细分析
                if subject and subject in ["语文", "数学", "英语", "物理"]:
                    result += self._analyze_subject_detail(class_name=cc, subject=subject)
                return result
        
        # 都匹配不到，调用AI智能分析
        return self._handle_free_chat(f"分析{f'{target}班' if '班' not in target else target}的成绩情况，请根据数据给出分析建议")
    
    def _analyze_subject_detail(self, class_name, subject):
        """单科详细分析"""
        data = self.db.cur.execute(f'''
            SELECT s.name, sc.{subject}
            FROM student s LEFT JOIN score sc ON s.sid=sc.sid
            WHERE s.class=?
            ORDER BY sc.{subject} DESC
        ''', (class_name,)).fetchall()
        
        if not data:
            return ""
        
        scores = [d[1] for d in data]
        avg = sum(scores) / len(scores)
        max_s = max(scores)
        min_s = min(scores)
        
        detail = f"\n▶ {subject}详细分析：\n"
        detail += f"   班级平均分：{avg:.1f}\n"
        detail += f"   最高分：{max_s}（{data[0][0]}） 最低分：{min_s}（{data[-1][0]}）\n"
        
        # 分段统计
        excellent = [(d[0], d[1]) for d in data if d[1] >= 90]
        good = [(d[0], d[1]) for d in data if 80 <= d[1] < 90]
        pass_s = [(d[0], d[1]) for d in data if 60 <= d[1] < 80]
        fail = [(d[0], d[1]) for d in data if d[1] < 60]
        
        detail += f"   优秀(>=90)：{len(excellent)}人"
        if excellent:
            detail += f"（{', '.join([f'{n}({s}分)' for n, s in excellent])}）"
        detail += "\n"
        
        detail += f"   良好(80-89)：{len(good)}人\n"
        detail += f"   及格(60-79)：{len(pass_s)}人\n"
        detail += f"   不及格(<60)：{len(fail)}人"
        if fail:
            detail += f"（{', '.join([f'{n}({s}分)' for n, s in fail])}）"
        detail += "\n"
        
        return detail

    def _handle_free_chat(self, user_text):
        """调用AI进行自由对话"""
        messages = [
            {"role": "system", "content": "你是一个智能化的学生成绩管理系统助手，名为'智析云途'。你可以回答关于成绩管理的一般性问题，给出学习建议，或者进行友好的日常对话。回答要简洁、友好、有温度，控制在100字以内。"},
            {"role": "user", "content": user_text}
        ]
        response = self.ai.call_api(messages, temperature=0.8, max_tokens=300)
        if response:
            return f"🤖 智析云途AI：\n{response}"
        else:
            return "🤖 暂时无法连接到AI服务，请检查网络连接或稍后重试。\n\n您也可以尝试以下固定指令：\n• 显示所有学生成绩\n• 总分/语文/数学/英语/物理排名\n• 分析[班级/年级]成绩\n• 修改[姓名]的[科目]成绩为[分数]\n• 删除学生[姓名]\n• 导出Excel"
    
    def _generate_comment(self, action, result):
        """生成人性化AI点评"""
        messages = [
            {"role": "system", "content": "你是学生成绩管理系统的AI助手。请根据用户的操作和结果数据，生成一句简短（50字以内）、亲切、有温度的人性化点评。点评要自然，不要过于机械，可以带点小表情。不需要重复数据，只需要一句温暖的点评或建议。"},
            {"role": "user", "content": f"用户执行了操作：{action}\n结果：{result[:200]}"}
        ]
        response = self.ai.call_api(messages, temperature=0.9, max_tokens=100)
        if response:
            return f"💬 AI小评：{response.strip()}"
        return ""


# ===================== 主界面 =====================
class MainWindow(QMainWindow):
    def __init__(self, db, ai):
        super().__init__()
        self.db = db
        self.ai = ai
        self.setWindowTitle("智析云途 - AI学生成绩管理系统 v2.0")
        self.resize(1000, 850)
        self.init_ui()
        self.setup_menu()

    def init_ui(self):
        # 主显示区域
        self.chat_display = QTextBrowser()
        self.chat_display.setFont(QFont("Microsoft YaHei", 10))
        self.chat_display.setStyleSheet("""
            QTextBrowser {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        
        # 快捷按钮区域
        btn_frame = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 5, 0, 5)
        
        buttons = [
            ("📋 显示全部", self.show_all),
            ("🏆 总分排名", lambda: self.send_command("总分排名")),
            ("📊 班级排名", lambda: self.send_command("高一1班排名")),
            ("📈 年级排名", lambda: self.send_command("高一年级排名")),
            ("📤 导出Excel", lambda: self.send_command("导出excel")),
        ]
        
        for text, func in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #4a90d9;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #357abd;
                }
                QPushButton:pressed {
                    background-color: #2a5f9e;
                }
            """)
            btn.clicked.connect(func)
            btn_layout.addWidget(btn)
        
        btn_frame.setLayout(btn_layout)
        
        # 输入区域
        input_frame = QWidget()
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入指令，如：显示所有学生 / 分析高一1班成绩 / 总分排名 / 随便聊聊...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                border: 2px solid #4a90d9;
                border-radius: 5px;
                padding: 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #357abd;
            }
        """)
        self.input_box.returnPressed.connect(self.send_message)
        
        send_btn = QPushButton("发送")
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a90d9;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
            QPushButton:pressed {
                background-color: #2a5f9e;
            }
        """)
        send_btn.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(send_btn)
        input_frame.setLayout(input_layout)
        
        # 主布局
        layout = QVBoxLayout()
        layout.addWidget(btn_frame)
        layout.addWidget(self.chat_display)
        layout.addWidget(input_frame)
        
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        # 欢迎信息
        self.chat_display.append("=" * 100)
        self.chat_display.append("🤖 欢迎使用智析云途 AI 学生成绩管理系统 v2.0 🎉")
        self.chat_display.append("")
        self.chat_display.append("📌 固定指令示例：")
        self.chat_display.append("   • 「显示所有学生」- 查看全部学生成绩")
        self.chat_display.append("   • 「总分排名」「语文排名」「数学排名」「英语排名」「物理排名」- 全校排名")
        self.chat_display.append("   • 「高一1班排名」「高二年级排名」「1班数学排名」- 班级/年级排名")
        self.chat_display.append("   • 「分析高一1班成绩」「分析高二年级成绩」- AI智能分析")
        self.chat_display.append("   • 「修改张三数学成绩95」- 修改成绩")
        self.chat_display.append("   • 「删除李四」- 删除学生")
        self.chat_display.append("   • 「添加学生 01020006 王小二 男 75 82 90 68」- 添加学生（学号规则：GGCCNNNN）")
        self.chat_display.append("   • 「导出Excel」- 导出成绩表格")
        self.chat_display.append("")
        self.chat_display.append("💡 学号标准：8位数字 GGCCNNNN（G=年级 C=班级 N=序号）")
        self.chat_display.append("   例如：01010001 = 高一1班第1号学生")
        self.chat_display.append("")
        self.chat_display.append("💬 也可以和我自由聊天，比如「今天心情不好」「给点学习建议」等")
        self.chat_display.append("=" * 100)
        self.chat_display.append("")

    def setup_menu(self):
        menubar = self.menuBar()
        
        # 系统菜单
        sys_menu = menubar.addMenu("系统")
        
        export_action = QAction("导出Excel", self)
        export_action.triggered.connect(lambda: self.send_command("导出excel"))
        sys_menu.addAction(export_action)
        
        sys_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        sys_menu.addAction(exit_action)
        
        # 查看菜单
        view_menu = menubar.addMenu("查看")
        
        all_action = QAction("显示所有学生", self)
        all_action.triggered.connect(self.show_all)
        view_menu.addAction(all_action)
        
        view_menu.addSeparator()
        
        rank_menu = view_menu.addMenu("排名")
        for name, field in [("总分排名", "总分"), ("语文排名", "语文"), ("数学排名", "数学"), ("英语排名", "英语"), ("物理排名", "物理")]:
            action = QAction(name, self)
            action.triggered.connect(lambda checked, f=field: self.send_command(f"{f}排名"))
            rank_menu.addAction(action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("学号标准", self)
        about_action.triggered.connect(lambda: self.show_info("学号标准", "学号格式：GGCCNNNN（8位数字）\nGG=年级(01高一/02高二/03高三)\nCC=班级编号(01-30)\nNNNN=顺序号(0001-9999)\n\n示例：01010001 = 高一1班第1号学生"))
        help_menu.addAction(about_action)

    def show_info(self, title, content):
        QMessageBox.information(self, title, content)

    def show_all(self):
        """显示所有学生（通过AI处理）"""
        self.send_command("显示所有学生")

    def send_command(self, text):
        """发送预设指令"""
        self.input_box.setText(text)
        self.send_message()

    def send_message(self):
        text = self.input_box.text().strip()
        if not text:
            return
        
        if len(text) > 500:
            self.chat_display.append("👤 你：[输入过长，已截断]" + text[:200] + "...")
            text = text[:500]
        else:
            self.chat_display.append(f"👤 你：{text}")
        
        self.input_box.clear()

        self.chat_display.append("🤖 AI：思考中，请稍候...⏳")
        QApplication.processEvents()

        worker = AIWorker(self.ai, self.db, text)
        worker.signals.done.connect(self.show_result)
        worker.signals.error.connect(self.show_error)
        QThreadPool.globalInstance().start(worker)

    def show_result(self, result):
        # 移除"思考中"的行
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_display.setTextCursor(cursor)
        
        # 查找最后一行"思考中"并删除
        doc = self.chat_display.document()
        block = doc.lastBlock()
        if block.text().strip() == "🤖 AI：思考中，请稍候...⏳":
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.End)
            cursor.movePosition(cursor.StartOfBlock, cursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 删除换行
            self.chat_display.setTextCursor(cursor)
        
        # 在等宽字体中显示表格结果更整齐
        if "学号" in result and "姓名" in result:
            font = QFont("Consolas", 10)
        else:
            font = QFont("Microsoft YaHei", 10)
        
        self.chat_display.setCurrentCharFormat(QTextCharFormat())
        fmt = QTextCharFormat()
        fmt.setFont(font)
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(f"\n🤖 AI：\n{result}\n\n", fmt)
    
    def show_error(self, error_msg):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        
        block = self.chat_display.document().lastBlock()
        if block.text().strip() == "🤖 AI：思考中，请稍候...⏳":
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.End)
            cursor.movePosition(cursor.StartOfBlock, cursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deleteChar()
            self.chat_display.setTextCursor(cursor)
        
        self.chat_display.append(f"🤖 AI：\n{error_msg}\n")


# ===================== 登录界面 =====================
class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("智析云途 - 登录")
        self.setFixedSize(350, 250)
        self.setStyleSheet("""
            QDialog {
                background-color: #f0f4f8;
            }
            QLabel {
                font-size: 13px;
                color: #333;
            }
            QLineEdit {
                border: 2px solid #4a90d9;
                border-radius: 5px;
                padding: 8px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #4a90d9;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
        """)
        
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("默认账号：admin")
        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("默认密码：123456")
        self.pwd_input.setEchoMode(QLineEdit.Password)
        
        self.login_btn = QPushButton("🔐 登录系统")
        self.login_btn.clicked.connect(self.check_login)
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addStretch()
        layout.addWidget(QLabel("👤 账号"))
        layout.addWidget(self.user_input)
        layout.addWidget(QLabel("🔑 密码"))
        layout.addWidget(self.pwd_input)
        layout.addSpacing(10)
        layout.addWidget(self.login_btn)
        layout.addStretch()
        self.setLayout(layout)
        
        self.user_input.setText("admin")
        self.pwd_input.returnPressed.connect(self.check_login)

    def check_login(self):
        username = self.user_input.text().strip()
        pwd = hashlib.md5(self.pwd_input.text().encode()).hexdigest()
        admin_pwd = hashlib.md5("123456".encode()).hexdigest()
        if username == "admin" and pwd == admin_pwd:
            self.accept()
        else:
            QMessageBox.warning(self, "登录失败", "账号或密码错误！\n默认账号：admin  密码：123456")


# ===================== 启动 =====================
if __name__ == "__main__":
    ai = DoubaoAI()
    db = Database()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    
    login = LoginDialog(db)
    if login.exec_() == QDialog.Accepted:
        window = MainWindow(db, ai)
        window.show()
        sys.exit(app.exec_())
