"""
Data loading and validation module
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
from src.config import Config
import os
import json

class DataLoader:
    def __init__(self, excel_file: str):
        self.excel_file = excel_file
        self.df = None
        self.df_teachers = None
        self.subjects = []
        self.semester_type = None
        self.teacher_initials = {}  # Full name -> Initials mapping
        self.teacher_ranks = {}     # Full name -> rank (lowercase, one of TEACHER_RANK_HOUR_CAPS keys)
        # Soft-only: initials -> {"off_days": [day_idx,...],
        #                         "preferred_slots": [in-day slot idx,...],
        #                         "avoid_slots":     [in-day slot idx,...]}
        self.teacher_preferences = {}

    def load_data(self) -> bool:
        """Load data from Excel file (Subjects + Teachers, plus optional Teacher Preferences)."""
        try:
            # Load main subjects sheet
            self.df = pd.read_excel(self.excel_file, sheet_name="Subjects")
            print(f"✅ Loaded {len(self.df)} rows from Subjects sheet")

            # Load teachers sheet
            self.df_teachers = pd.read_excel(self.excel_file, sheet_name="Teachers")
            print(f"✅ Loaded {len(self.df_teachers)} teachers from Teachers sheet")

            # Validate the Teachers sheet BEFORE building the initials map so a
            # partial / inconsistent map can't leak into downstream processing.
            self._validate_teachers_sheet()

            from src.config import Config
            has_rank_col = "Rank" in self.df_teachers.columns
            missing_rank_warned = False

            for idx, row in self.df_teachers.iterrows():
                full_name = str(row["Full Name"]).strip()
                initials = str(row["Initials"]).strip()
                self.teacher_initials[full_name] = initials

                # Rank column is optional; if absent, every teacher defaults to
                # Assistant. If present but blank for an individual row, warn
                # per teacher so the user notices unintentional gaps.
                rank = Config.DEFAULT_TEACHER_RANK
                if has_rank_col:
                    raw = row.get("Rank")
                    if pd.isna(raw) or not str(raw).strip():
                        print(f"⚠️  Teacher '{full_name}' (row {idx + 2}) has no Rank — "
                              f"defaulting to {Config.DEFAULT_TEACHER_RANK.title()} "
                              f"({Config.TEACHER_RANK_HOUR_CAPS[Config.DEFAULT_TEACHER_RANK]}h cap)")
                    else:
                        rank = str(raw).strip().lower()
                self.teacher_ranks[full_name] = rank

            if not has_rank_col:
                print(f"⚠️  Teachers sheet has no 'Rank' column — all {len(self.teacher_ranks)} "
                      f"teachers default to {Config.DEFAULT_TEACHER_RANK.title()} "
                      f"({Config.TEACHER_RANK_HOUR_CAPS[Config.DEFAULT_TEACHER_RANK]}h cap)")

            # Optional Teacher Preferences sheet — pure soft constraints, never
            # raise infeasibility, silently skipped if the sheet doesn't exist.
            self._load_teacher_preferences()

            return True
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            return False

    def _load_teacher_preferences(self):
        """
        Parse the optional 'Teacher Preferences' sheet. Absent sheet or absent
        teacher rows → silent skip (preferences are soft-only).
        """
        try:
            df_prefs = pd.read_excel(self.excel_file, sheet_name="Teacher Preferences")
        except Exception:
            return  # sheet not present — fine

        if df_prefs.empty:
            return

        from src.config import Config

        # Tolerate extra/missing optional cols; only "Full Name" is mandatory
        # to identify the teacher. Missing per-row fields are treated as "no
        # preference of that kind".
        if "Full Name" not in df_prefs.columns:
            raise ValueError(
                "Teacher Preferences sheet is missing 'Full Name' column. "
                "Expected columns: Full Name, Off Days, Preferred Time, Avoid Time."
            )

        # Track unknown names to surface as a single error message — common typo.
        unknown_names = []

        for idx, row in df_prefs.iterrows():
            row_no = idx + 2  # excel row number with header
            name_raw = row.get("Full Name")
            if pd.isna(name_raw):
                continue
            full_name = str(name_raw).strip()
            if not full_name:
                continue

            if full_name not in self.teacher_initials:
                unknown_names.append((row_no, full_name))
                continue

            initials = self.teacher_initials[full_name]
            entry = {"off_days": [], "preferred_slots": [], "avoid_slots": []}

            # Off Days
            off_raw = row.get("Off Days")
            if not pd.isna(off_raw) and str(off_raw).strip():
                for token in str(off_raw).split(","):
                    token = token.strip().lower()
                    if not token:
                        continue
                    if token not in Config.DAY_NAME_TO_INDEX:
                        raise ValueError(
                            f"Teacher Preferences row {row_no}: unknown day '{token}' "
                            f"in 'Off Days'. Use Mon/Tue/.../Sat or Monday/Tuesday/...."
                        )
                    entry["off_days"].append(Config.DAY_NAME_TO_INDEX[token])

            # Preferred Time
            pref_raw = row.get("Preferred Time")
            if not pd.isna(pref_raw) and str(pref_raw).strip():
                label = str(pref_raw).strip().title()  # "morning" -> "Morning"
                if label not in Config.PREFERRED_TIME_SLOTS:
                    raise ValueError(
                        f"Teacher Preferences row {row_no}: unknown 'Preferred Time' "
                        f"label '{pref_raw}'. Allowed: {list(Config.PREFERRED_TIME_SLOTS.keys())}."
                    )
                entry["preferred_slots"] = list(Config.PREFERRED_TIME_SLOTS[label])

            # Avoid Time
            avoid_raw = row.get("Avoid Time")
            if not pd.isna(avoid_raw) and str(avoid_raw).strip():
                label = str(avoid_raw).strip().title()
                if label not in Config.PREFERRED_TIME_SLOTS:
                    raise ValueError(
                        f"Teacher Preferences row {row_no}: unknown 'Avoid Time' "
                        f"label '{avoid_raw}'. Allowed: {list(Config.PREFERRED_TIME_SLOTS.keys())}."
                    )
                entry["avoid_slots"] = list(Config.PREFERRED_TIME_SLOTS[label])

            # Skip rows that contributed no preferences after parsing
            if entry["off_days"] or entry["preferred_slots"] or entry["avoid_slots"]:
                self.teacher_preferences[initials] = entry

        if unknown_names:
            details = "; ".join(f"row {n} ('{nm}')" for n, nm in unknown_names)
            raise ValueError(
                f"Teacher Preferences references unknown teacher(s): {details}. "
                f"Full Name must match Teachers sheet exactly."
            )

        if self.teacher_preferences:
            print(f"✅ Loaded preferences for {len(self.teacher_preferences)} teacher(s)")

    def _validate_teachers_sheet(self):
        """
        Enforce that every teacher row has non-blank initials and that no two
        teachers share the same initials. Raised early — before model building —
        so the user gets immediate, actionable feedback instead of a confusing
        downstream error (split-teaching event IDs and several constraints key
        off initials, so duplicates would silently merge teachers' constraints).
        """
        required_cols = ["Full Name", "Initials"]
        missing = [c for c in required_cols if c not in self.df_teachers.columns]
        if missing:
            raise ValueError(
                f"Teachers sheet is missing required column(s): {missing}. "
                f"Expected columns: {required_cols}."
            )

        # Blank / missing initials check
        blank_rows = []
        for idx, row in self.df_teachers.iterrows():
            initials_raw = row["Initials"]
            initials = "" if pd.isna(initials_raw) else str(initials_raw).strip()
            full_name = "" if pd.isna(row["Full Name"]) else str(row["Full Name"]).strip()
            if not initials or initials.lower() == "nan":
                blank_rows.append((idx + 2, full_name or "<blank name>"))

        if blank_rows:
            details = "; ".join(f"row {n} (Full Name: '{name}')" for n, name in blank_rows)
            raise ValueError(
                f"Blank or missing Initials in Teachers sheet for: {details}. "
                f"Every teacher must have a non-empty Initials value."
            )

        # Duplicate-initials check (case-sensitive: "MK" and "mk" treated as
        # different on purpose, since the existing constraint code uses initials
        # verbatim in event IDs).
        from collections import defaultdict
        names_by_initials = defaultdict(list)
        for idx, row in self.df_teachers.iterrows():
            initials = str(row["Initials"]).strip()
            full_name = str(row["Full Name"]).strip()
            names_by_initials[initials].append((idx + 2, full_name))

        conflicts = {ini: rows for ini, rows in names_by_initials.items() if len(rows) > 1}
        if conflicts:
            lines = []
            for ini, rows in conflicts.items():
                names = ", ".join(f"'{name}' (row {n})" for n, name in rows)
                lines.append(f"'{ini}' is used by {names}")
            raise ValueError(
                "Duplicate initials found: "
                + "; ".join(lines)
                + ". Initials must be unique across all teachers."
            )

        # Rank column is OPTIONAL: absent column → every teacher defaults to
        # Assistant. Present column → each non-blank cell must be a valid rank.
        if "Rank" in self.df_teachers.columns:
            from src.config import Config
            allowed = set(Config.TEACHER_RANK_HOUR_CAPS.keys())
            for idx, row in self.df_teachers.iterrows():
                raw = row.get("Rank")
                if pd.isna(raw) or not str(raw).strip():
                    continue  # blank handled with warning + default in load_data
                normalized = str(raw).strip().lower()
                if normalized not in allowed:
                    full_name = str(row["Full Name"]).strip()
                    raise ValueError(
                        f"Unknown rank '{raw}' for teacher '{full_name}' (row {idx + 2}). "
                        f"Must be one of: {', '.join(s.title() for s in allowed)}"
                    )
    
    def validate_data(self) -> bool:
        """Validate the loaded data"""
        if not self.load_data():
            return False
        
        # Check required columns
        required_columns = [
            "Course", "Semester", "Subject", "Section", "Teacher", 
            "Hours Taught(Le,Tu,Pr)", "Department", "Subject_type", "Has_Lab"
        ]
        missing_columns = [col for col in required_columns if col not in self.df.columns]
        
        if missing_columns:
            print(f"❌ Missing required columns: {missing_columns}")
            return False
        
        # Validate semester type
        if not self._validate_semester_type():
            return False
        
        # Validate each row
        for idx, row in self.df.iterrows():
            if not self._validate_row(idx, row):
                return False
        
        # Parse hour requirements and expand sections
        self._parse_and_expand_subjects()
        
        print("✅ Data validation passed")
        return True
    
    def _validate_semester_type(self) -> bool:
        """Validate semester type (now reads from ConfigManager via main.py)"""
        # Note: semester_type is now set by main.py from ConfigManager
        # before validate_data() is called
        
        if not hasattr(self, 'semester_type') or self.semester_type is None:
            print("❌ Semester type not set. This should be set by main.py")
            return False
        
        if self.semester_type == "odd":
            valid_semesters = Config.ODD_SEMESTERS
        elif self.semester_type == "even":
            valid_semesters = Config.EVEN_SEMESTERS
        else:
            print(f"❌ Invalid semester_type: {self.semester_type}")
            return False
        
        # Check if all semesters in data match the selected type
        unique_semesters = self.df["Semester"].unique()
        invalid_semesters = [s for s in unique_semesters if s not in valid_semesters]
        
        if invalid_semesters:
            print(f"❌ Invalid semesters found: {invalid_semesters}")
            print(f"   Expected: {valid_semesters}")
            print(f"   Current semester type: {self.semester_type.upper()}")
            return False
        
        print(f"✅ Semester type: {self.semester_type.upper()} - Valid semesters: {list(unique_semesters)}")
        return True
    
    def _validate_hours_taught(self, hours_str: str, subject_type: str, has_lab: bool, 
                        row_num: int, teacher_str: str) -> bool:
        """Validate hours taught format - supports pipe-separated hours for split teaching"""
        try:
            # Check if pipe-separated (split teaching with explicit hours)
            if "|" in teacher_str and "|" in hours_str:
                teacher_parts = [t.strip() for t in teacher_str.split("|")]
                hours_parts = [h.strip() for h in hours_str.split("|")]
                
                #Checking matching number of teachers and hours parts
                if len(teacher_parts) != len(hours_parts):
                    print(f"❌ Row {row_num}: Mismatch between teachers ({len(teacher_parts)}) and hour entries ({len(hours_parts)})")
                    print(f"   When using '|' in teachers, must have matching '|' in hours")
                    return False
                
                # Validate each teacher's hours
                total_le, total_tu, total_pr = 0, 0, 0
                
                for i, hours_part in enumerate(hours_parts):
                    parts = [p.strip() for p in hours_part.split(",")]
                    
                    if len(parts) != 3:
                        print(f"❌ Row {row_num}: Invalid hours format for teacher {i+1}: '{hours_part}'")
                        print(f"   Expected format: 'Le,Tu,Pr' (e.g., '2,0,1')")
                        return False
                    
                    le, tu, pr = [int(p) for p in parts]
                    if le < 0 or tu < 0 or pr < 0:
                        print(f"❌ Row {row_num}: Hours cannot be negative for teacher {i+1}")
                        return False
                    
                    total_le += le
                    total_tu += tu
                    total_pr += pr
                
                # Now validate totals against requirement
                requirement = Config.get_subject_requirement(subject_type, has_lab)
                
                if total_le > requirement["Le"]:
                    print(f"❌ Row {row_num}: Combined lecture hours ({total_le}) exceed requirement ({requirement['Le']})")
                    return False
                
                if total_tu > requirement["Tu"]:
                    print(f"❌ Row {row_num}: Combined tutorial hours ({total_tu}) exceed requirement ({requirement['Tu']})")
                    return False
                
                if total_pr > requirement["Pr"]:
                    print(f"❌ Row {row_num}: Combined practical hours ({total_pr}) exceed requirement ({requirement['Pr']})")
                    return False
                
                # Validate Has_Lab consistency
                if has_lab and requirement["Pr"] == 0:
                    print(f"❌ Row {row_num}: Has_Lab is 'Yes' but subject type '{subject_type}' has no practical component")
                    return False
                
                if not has_lab and total_pr > 0:
                    print(f"❌ Row {row_num}: Has_Lab is 'No' but Hours Taught shows {total_pr} practical hours")
                    return False
                
                return True
            
            else:
                # Single teacher (existing logic)
                parts = [p.strip() for p in hours_str.split(",")]
                
                if len(parts) != 3:
                    print(f"❌ Row {row_num}: Invalid hours format '{hours_str}'")
                    print(f"   Expected format: 'Le,Tu,Pr' (e.g., '3,0,2' or '3,1,0' or 0,0,4, etc.)")
                    return False
                
                le, tu, pr = [int(p) for p in parts]
                if le < 0 or tu < 0 or pr < 0:
                    print(f"❌ Row {row_num}: Hours cannot be negative")
                    return False
                
                requirement = Config.get_subject_requirement(subject_type, has_lab)
                
                if le > requirement["Le"]:
                    print(f"❌ Row {row_num}: Lecture hours ({le}) exceed requirement ({requirement['Le']})")
                    return False
                
                if tu > requirement["Tu"]:
                    print(f"❌ Row {row_num}: Tutorial hours ({tu}) exceed requirement ({requirement['Tu']})")
                    return False
                
                if pr > requirement["Pr"]:
                    print(f"❌ Row {row_num}: Practical hours ({pr}) exceed requirement ({requirement['Pr']})")
                    return False
                
                if has_lab and requirement["Pr"] == 0:
                    print(f"❌ Row {row_num}: Has_Lab is 'Yes' but subject type '{subject_type}' has no practical component")
                    return False
                
                if not has_lab and pr > 0:
                    print(f"❌ Row {row_num}: Has_Lab is 'No' but Hours Taught shows {pr} practical hours")
                    return False
                
                return True
        
        except ValueError:
            print(f"❌ Row {row_num}: Invalid hours format '{hours_str}'")
            print(f"   All values must be integers")
            return False

    def _validate_row(self, idx: int, row: pd.Series) -> bool:
        """Validate a single row"""
        row_num = idx + 2  # Excel row number (1-indexed + header)
        
        # Get subject type first (MANDATORY)
        subject_type_raw = row["Subject_type"]
        if pd.isna(subject_type_raw) or str(subject_type_raw).strip() == "":
            print(f"❌ Row {row_num}: Subject_type cannot be empty")
            print(f"   Must be one of: {Config.SUBJECT_TYPES}")
            return False
        
        subject_type = str(subject_type_raw).strip().upper()
        
        # Validate semester
        if not isinstance(row["Semester"], (int, np.integer)):
            print(f"❌ Row {row_num}: Semester must be a number, got '{row['Semester']}'")
            return False
        
        semester = int(row["Semester"])
        
        # Check for empty values (Course[for GE/SEC/VAC/AEC] and Section can be empty, Has_Lab and Subject_type handled later)
        required_cols = ["Semester", "Subject", "Teacher", "Hours Taught(Le,Tu,Pr)", "Department"]
        for col in required_cols:
            if pd.isna(row[col]) or str(row[col]).strip() == "":
                print(f"❌ Row {row_num}: Empty value in column '{col}'")
                return False
        
        # Course validation - can be empty only for GE/SEC/VAC/AEC
        if pd.isna(row["Course"]) or str(row["Course"]).strip() == "":
            if subject_type not in ["GE", "SEC", "VAC", "AEC"]:
                print(f"❌ Row {row_num}: Course cannot be empty for non-GE/SEC/VAC/AEC subjects")
                print(f"   Subject type: {subject_type}")
                return False
        
        # Section validation - Required for all subject types for when subjects repeats with same semester in rows
        # For now, just get the value (we'll validate repetition later in post-processing)
        if pd.isna(row["Section"]) or str(row["Section"]).strip() == "":
            section = ""  # Will auto-assign later if needed
        else:
            # Handle NaN (empty) sections from pandas
            if pd.notna(row["Section"]) and str(row["Section"]).strip():
                section = str(row["Section"]).strip().upper()
            else:
                section = ""

        # Validate Has_Lab column
        if pd.isna(row["Has_Lab"]):
            print(f"❌ Row {row_num}: Has_Lab cannot be empty")
            return False

        has_lab_str = str(row["Has_Lab"]).strip().lower()
        if has_lab_str not in ["yes", "no"]:
            print(f"❌ Row {row_num}: Has_Lab must be 'Yes' or 'No', got '{row['Has_Lab']}'")
            return False

        has_lab = (has_lab_str == "yes")

        # Parse teacher(s) - can be comma or pipe separated
        teacher_str = str(row["Teacher"]).strip()

        # Check for split teaching (pipe) vs co-teaching (comma)
        if "|" in teacher_str:
            teachers = [t.strip() for t in teacher_str.split("|")]
        else:
            teachers = [t.strip() for t in teacher_str.split(",")]

        # Validate all teachers exist in teacher sheet
        for teacher in teachers:
            if teacher not in self.teacher_initials:
                print(f"❌ Row {row_num}: Teacher '{teacher}' not found in Teachers sheet")
                return False

        num_teachers = len(teachers)

        # Validate hours taught format (actual hours)
        hours_taught = str(row["Hours Taught(Le,Tu,Pr)"]).strip()
        teacher_str = str(row["Teacher"]).strip()
        if not self._validate_hours_taught(hours_taught, subject_type, has_lab, row_num, teacher_str):
            return False
        
        # Validate Subject_type
        if not pd.isna(row["Subject_type"]):
            if subject_type not in Config.SUBJECT_TYPES:
                print(f"❌ Row {row_num}: Invalid Subject_type '{subject_type}'. Must be one of: {Config.SUBJECT_TYPES}")
                return False
            
            # Validate subject type is allowed for this semester
            allowed_types = Config.get_allowed_subject_types_for_semester(semester)
            if subject_type not in allowed_types:
                print(f"❌ Row {row_num}: Subject type '{subject_type}' not allowed for Semester {semester}")
                print(f"   Allowed types for Semester {semester}: {allowed_types}")
                return False
        
        # Validate course exists in config (if specified)
        if not pd.isna(row["Course"]) and str(row["Course"]).strip() != "":
            course_input = str(row["Course"]).strip()
            
            # Handle multiple courses separated by '+' (e.g., "CS(H) + CA(P)")
            course_parts = [c.strip() for c in course_input.split("+")]
            
            for course_part in course_parts:
                # Convert short form to full name if needed
                course = Config.get_full_course_name(course_part)
                
                # Check if conversion worked (if input was invalid, it returns as-is)
                if course not in Config.COURSE_SECTIONS:
                    print(f"❌ Row {row_num}: Course '{course_part}' not found in system configuration")
                    print(f"   Available short forms: {list(Config.COURSE_SHORT_FORMS.keys())}")
                    print(f"   Or use full names: {list(Config.COURSE_SECTIONS.keys())}")
                    return False
        
        return True

    def _parse_and_expand_subjects(self):
        """Parse hour requirements and expand subjects into course-section combinations"""
        self.subjects = []
        
        # First pass: Group GE/SEC/VAC/AEC subjects by (semester, subject_name, subject_type)
        ge_sec_vac_aec_groups = {}
        regular_subjects = []
        
        for idx, row in self.df.iterrows():
            # Parse hours taught - handle pipe-separated for split teaching
            hours_taught = str(row["Hours Taught(Le,Tu,Pr)"]).strip()
            teacher_str = str(row["Teacher"]).strip()
            
            # Get Has_Lab flag
            has_lab = str(row["Has_Lab"]).strip().lower() == "yes"
            
            # Get subject type (validated already)
            subject_type = str(row["Subject_type"]).strip().upper()
            
            # Get section from Excel
            if pd.notna(row["Section"]) and str(row["Section"]).strip():
                section = str(row["Section"]).strip().upper()
            else:
                section = ""
            
            # Normalize names
            subject_name = " ".join(str(row["Subject"]).strip().split())
            department = str(row["Department"]).strip()
            semester = int(row["Semester"])
            
            # Determine room type for practicals
            if has_lab:
                lab_type = Config.DEPARTMENT_LABS.get(department, "Lab-General")
            else:
                lab_type = None
                
            if "|" in teacher_str and "|" in hours_taught:
                is_split_teaching = True
                split_group_id = f"split_{semester}_{subject_name}_{section}_{idx}".replace(" ", "_")
            else:
                is_split_teaching = False
                split_group_id = None
            
            # ================================================================
            # SPLIT TEACHING: Loop through each teacher and create separate entries
            # ================================================================
            if "|" in teacher_str and "|" in hours_taught:
                teachers = [t.strip() for t in teacher_str.split("|")]
                hours_parts = [h.strip() for h in hours_taught.split("|")]
                
                # Generate Split_Group_ID for coordination
                split_group_id = f"split_{semester}_{subject_name}_{section}_{idx}".replace(" ", "_")
                # ✅ FIX: Loop through EACH teacher and create separate entry
                for teacher_idx, (teacher, hours_part) in enumerate(zip(teachers, hours_parts)):
                    # Parse THIS teacher's hours
                    parts = [int(x.strip()) for x in hours_part.split(",")]
                    taught_le, taught_tu, taught_pr = parts[0], parts[1], parts[2]
                    
                    # Calculate remaining hours needed
                    remaining = Config.calculate_remaining_hours(subject_type, has_lab, taught_le, taught_tu, taught_pr)
                    
                    # Total hours = what this teacher teaches
                    total_taught_hours = taught_le + taught_tu + taught_pr
                    
                    row_data = {
                        "semester": semester,
                        "subject_name": subject_name,
                        "section": section,
                        "main_teacher": teacher,  # THIS teacher
                        "co_teachers": [],  # No co-teachers in split teaching
                        "is_split_teaching": is_split_teaching,
                        "assistant_info": [],
                        "department": department,
                        "subject_type": subject_type,
                        "has_lab": has_lab,
                        "split_group_id": split_group_id,  # Same group ID for all teachers
                        "taught_lecture_hours": taught_le,
                        "taught_tutorial_hours": taught_tu,
                        "taught_practical_hours": taught_pr,
                        "remaining_lecture_hours": remaining["Le"],
                        "remaining_tutorial_hours": remaining["Tu"],
                        "remaining_practical_hours": remaining["Pr"],
                        "total_taught_hours": total_taught_hours,
                        "lab_type": lab_type
                    }
                    
                    # Add to appropriate group
                    if subject_type in ["GE", "SEC", "VAC", "AEC"]:
                        key = (semester, subject_name, subject_type)
                        if key not in ge_sec_vac_aec_groups:
                            ge_sec_vac_aec_groups[key] = []
                        ge_sec_vac_aec_groups[key].append(row_data)
                    else:
                        # Regular DSC/DSE subjects
                        course_input = " ".join(str(row["Course"]).strip().split())
                        course_parts = [c.strip() for c in course_input.split("+")]
                        
                        is_merged = len(course_parts) > 1
                        merge_group_id = f"merge_{semester}_{subject_name}_{idx}" if is_merged else None
                        
                        for course_part in course_parts:
                            course = Config.get_full_course_name(course_part)
                            row_data_copy = row_data.copy()
                            row_data_copy["course"] = course
                            row_data_copy["is_merged"] = is_merged
                            row_data_copy["merge_group_id"] = merge_group_id
                            regular_subjects.append(row_data_copy)

            # ================================================================
            # SINGLE TEACHER or CO-TEACHING
            # ================================================================
            else:
                parts = [int(x.strip()) for x in hours_taught.split(",")]
                taught_le, taught_tu, taught_pr = parts[0], parts[1], parts[2]
                
                teacher_list = [t.strip() for t in teacher_str.split(",")]
                main_teacher = teacher_list[0]
                co_teachers = teacher_list[1:] if len(teacher_list) > 1 else []
                
                # Calculate remaining hours
                remaining = Config.calculate_remaining_hours(subject_type, has_lab, taught_le, taught_tu, taught_pr)
                total_taught_hours = taught_le + taught_tu + taught_pr
                
                row_data = {
                    "semester": semester,
                    "subject_name": subject_name,
                    "section": section,
                    "main_teacher": main_teacher,
                    "co_teachers": co_teachers,
                    "is_split_teaching": is_split_teaching,
                    "assistant_info": [],
                    "department": department,
                    "subject_type": subject_type,
                    "has_lab": has_lab,
                    "split_group_id": None,
                    "taught_lecture_hours": taught_le,
                    "taught_tutorial_hours": taught_tu,
                    "taught_practical_hours": taught_pr,
                    "remaining_lecture_hours": remaining["Le"],
                    "remaining_tutorial_hours": remaining["Tu"],
                    "remaining_practical_hours": remaining["Pr"],
                    "total_taught_hours": total_taught_hours,
                    "lab_type": lab_type
                }
                
                # Add to appropriate group
                if subject_type in ["GE", "SEC", "VAC", "AEC"]:
                    key = (semester, subject_name, subject_type)
                    if key not in ge_sec_vac_aec_groups:
                        ge_sec_vac_aec_groups[key] = []
                    ge_sec_vac_aec_groups[key].append(row_data)
                else:
                    course_input = " ".join(str(row["Course"]).strip().split())
                    course_parts = [c.strip() for c in course_input.split("+")]
                    
                    is_merged = len(course_parts) > 1
                    merge_group_id = f"merge_{semester}_{subject_name}_{idx}" if is_merged else None
                    
                    for course_part in course_parts:
                        course = Config.get_full_course_name(course_part)
                        row_data_copy = row_data.copy()
                        row_data_copy["course"] = course
                        row_data_copy["is_merged"] = is_merged
                        row_data_copy["merge_group_id"] = merge_group_id
                        regular_subjects.append(row_data_copy)

        # Process GE/SEC/VAC/AEC subjects with proper sections
        for (semester, subject_name, subject_type), teachers_data in ge_sec_vac_aec_groups.items():
            # Auto-assign sections if needed
            if len(teachers_data) == 1:
                # Single teacher - use "A" if empty
                if not teachers_data[0]["section"]:
                    teachers_data[0]["section"] = "A"
            else:
                # Multiple teachers - check if they're split teaching (same split_group_id)
                # or different sections (different split_group_id or no split_group_id)
                
                split_groups = {}
                for teacher_data in teachers_data:
                    split_id = teacher_data.get("split_group_id")
                    if split_id:
                        if split_id not in split_groups:
                            split_groups[split_id] = []
                        split_groups[split_id].append(teacher_data)
                
                # For split teaching groups, all teachers share the same section (OK)
                # For non-split teaching, sections MUST be different
                
                non_split_teachers = [td for td in teachers_data if not td.get("split_group_id")]
                
                # Check non-split teachers have sections specified
                if len(non_split_teachers) > 1:
                    for teacher_data in non_split_teachers:
                        if not teacher_data["section"]:
                            print(f"❌ ERROR: {subject_type} '{subject_name}' Sem{semester} has {len(non_split_teachers)} separate entries")
                            print(f"   Sections must be specified (A, B, C, etc.) when subject repeats")
                            raise ValueError("Missing sections for repeated GE/SEC/VAC/AEC subject")
                
                # For split teaching groups, ensure they have section (can be same)
                for split_id, split_teachers in split_groups.items():
                    # All should have the same section
                    sections = [td["section"] for td in split_teachers]
                    if any(not s for s in sections):
                        # Some missing sections - assign "A" to all in group
                        for td in split_teachers:
                            td["section"] = "A"
            
            # Sort by section letter
            teachers_data.sort(key=lambda x: x["section"])
            
            for teacher_data in teachers_data:
                # Use section from Excel data (already validated/assigned)
                section_letter = teacher_data["section"]
                
                # Create unique Course_Semester ID
                subject_short = subject_name.replace(" ", "")[:15]
                # Always include section for GE/SEC/VAC (they commonly have multiple sections)
                course_semester = f"COMMON-{subject_type}-Sem{semester}-{subject_short}-Sec{section_letter}"
                
                # Determine if practical should use GE_LAB slots
                is_ge_lab = (subject_type == "GE" and has_lab)
                
                # Get requirement for this subject
                requirement = Config.get_subject_requirement(subject_type, teacher_data["has_lab"])

                subject_data = {
                    "Course": "COMMON",
                    "Semester": semester,
                    "Subject": subject_name,
                    "Teacher": teacher_data["main_teacher"],
                    "Is_Merged": False,  # NEW: GE/SEC/VAC never merged
                    "Merge_Group_ID": None,
                    "split_group_id": teacher_data["split_group_id"],
                    "Co_Teachers": teacher_data["co_teachers"],
                    "Is_Split_Teaching": teacher_data["is_split_teaching"],
                    "Assistant_Teachers": teacher_data["assistant_info"],
                    "Department": teacher_data["department"],
                    "Subject_type": subject_type,
                    "Has_Lab": teacher_data["has_lab"],
                    
                    # What this teacher teaches
                    "Taught_Lecture_hours": teacher_data["taught_lecture_hours"],
                    "Taught_Tutorial_hours": teacher_data["taught_tutorial_hours"],
                    "Taught_Practical_hours": teacher_data["taught_practical_hours"],
                    
                    # What's still needed (for assistant assignment)
                    "Remaining_Lecture_hours": teacher_data["remaining_lecture_hours"],
                    "Remaining_Tutorial_hours": teacher_data["remaining_tutorial_hours"],
                    "Remaining_Practical_hours": teacher_data["remaining_practical_hours"],
                    
                    # Full requirements (for solver)
                    "Lecture_hours": requirement["Le"],
                    "Tutorial_hours": requirement["Tu"],
                    "Practical_hours": requirement["Pr"],
                    
                    "Total_hours": requirement["Le"] + requirement["Tu"] + requirement["Pr"],
                    "Total_taught_hours": teacher_data["total_taught_hours"],
                    
                    "Lab_type": teacher_data["lab_type"] if teacher_data["taught_practical_hours"] > 0 else None,
                    "Course_Semester": course_semester,
                    "Section": section_letter,
                    "Students_count": Config.get_ge_sec_vac_strength(subject_type, semester, subject_name, section_letter),
                    "Is_GE_Lab": is_ge_lab
                }
                self.subjects.append(subject_data)

        # Validate sections for ALL subject types (DSC/DSE/GE/SEC/VAC)
        # Group by (course, semester, subject_name, subject_type) to detect same-subject repetitions
        subject_repetition_check = {}

        for idx, row in self.df.iterrows():
            course_input = str(row.get("Course", "COMMON")).strip()
            if not course_input: #In case of Nan
                course_input = "COMMON"
            
            semester = int(row["Semester"])
            subject_name = str(row["Subject"]).strip()
            subject_type = str(row["Subject_type"]).strip().upper()
            section = str(row.get("Section", "")).strip().upper() if pd.notna(row.get("Section")) else ""
            
            # Handle merged courses (take first course for grouping)
            if "+" in course_input:
                course_input = course_input.split("+")[0].strip()
            
            course = Config.get_full_course_name(course_input)
            
            key = (course, semester, subject_name, subject_type)
            if key not in subject_repetition_check:
                subject_repetition_check[key] = []
            subject_repetition_check[key].append((section, idx))

        # Check: If subject appears multiple times, sections MUST be specified
        for key, entries in subject_repetition_check.items():
            if len(entries) > 1:
                course, semester, subject_name, subject_type = key
                sections = [e[0] for e in entries]
                
                if any(not s for s in sections):
                    # Some entries missing sections
                    row_nums = [e[1] + 2 for e in entries]  # Excel row numbers
                    print(f"\n❌ ERROR: Subject '{subject_name}' ({subject_type}) for {course} Sem{semester}")
                    print(f"   appears {len(entries)} times (rows {row_nums})")
                    print(f"   All instances must have sections specified (A, B, C, etc.)")
                    raise ValueError("Missing sections for repeated subject")

        # Now group by course-semester-section
        regular_grouped = {}
        for subject_data in regular_subjects:
            course = subject_data["course"]
            semester = subject_data["semester"]
            section = subject_data["section"]
            key = (course, semester, section)
            
            if key not in regular_grouped:
                regular_grouped[key] = []
            regular_grouped[key].append(subject_data)

        # Create entries for each subject
        for (course, semester, section), subjects_list in regular_grouped.items():
            for subject_data in subjects_list:
                # Get requirement for this subject
                requirement = Config.get_subject_requirement(
                    subject_data["subject_type"],
                    subject_data["has_lab"]
                )
                
                # Build unique Course_Semester ID
                # If section exists, use it; otherwise use subject name for uniqueness
                if section:
                    course_semester_id = f"{course}-Sem{semester}-{section}"
                else:
                    # No section = single subject, use subject name for uniqueness
                    subject_short = subject_data["subject_name"].replace(" ", "")[:20]
                    course_semester_id = f"{course}-Sem{semester}-{subject_short}"                
                
                entry = {
                    "Course": course,
                    "Semester": semester,
                    "Subject": subject_data["subject_name"],
                    "Teacher": subject_data["main_teacher"],
                    "Is_Merged": subject_data.get("is_merged", False),
                    "Merge_Group_ID": subject_data.get("merge_group_id", None),
                    "split_group_id": subject_data["split_group_id"],
                    "Co_Teachers": subject_data["co_teachers"],
                    "Is_Split_Teaching": subject_data["is_split_teaching"],
                    "Assistant_Teachers": subject_data["assistant_info"],
                    "Department": subject_data["department"],
                    "Subject_type": subject_data["subject_type"],
                    "Has_Lab": subject_data["has_lab"],
                    
                    # What this teacher teaches
                    "Taught_Lecture_hours": subject_data["taught_lecture_hours"],
                    "Taught_Tutorial_hours": subject_data["taught_tutorial_hours"],
                    "Taught_Practical_hours": subject_data["taught_practical_hours"],
                    
                    # What's still needed
                    "Remaining_Lecture_hours": subject_data["remaining_lecture_hours"],
                    "Remaining_Tutorial_hours": subject_data["remaining_tutorial_hours"],
                    "Remaining_Practical_hours": subject_data["remaining_practical_hours"],
                    
                    # Full requirements
                    "Lecture_hours": requirement["Le"],
                    "Tutorial_hours": requirement["Tu"],
                    "Practical_hours": requirement["Pr"],
                    
                    "Total_hours": requirement["Le"] + requirement["Tu"] + requirement["Pr"],
                    "Total_taught_hours": subject_data["total_taught_hours"],
                    
                    "Lab_type": subject_data["lab_type"] if subject_data["taught_practical_hours"] > 0 else None,
                    # Include section in ID only if it exists
                    "Course_Semester": course_semester_id,
                    "Section": section if section else "",  # Keep empty if no section
                    "Students_count": Config.get_student_strength(course, semester, section),
                    "Is_GE_Lab": False
                }
                self.subjects.append(entry)

        print(f"✅ Parsed and expanded to {len(self.subjects)} subject-section combinations")
    
    def _count_teacher_hours_correctly(self, subjects_list):
        """
        Calculate teacher hours respecting merged courses (count once per merge group)
        Returns: {teacher: {"total": hours, "subjects": count, "details": [...]}}
        """
        teacher_hours = {}
        processed_merge_groups = set()  # Track which merge groups we've counted
        
        for subj in subjects_list:
            # Check if this is part of a merged course group
            is_merged = subj.get("Is_Merged", False)
            merge_group_id = subj.get("Merge_Group_ID")
            
            # Skip if we've already counted this merge group
            if is_merged and merge_group_id in processed_merge_groups:
                continue
            
            # Mark this merge group as processed
            if is_merged and merge_group_id:
                processed_merge_groups.add(merge_group_id)
            
            # Get teacher hours (respecting split teaching)
            main_teacher = subj["Teacher"]
            
            # For split teaching, use ACTUAL hours taught (not divided)
            # Total_taught_hours already represents what THIS teacher teaches
            main_hours = subj.get("Taught_Lecture_hours", 0) + subj.get("Taught_Tutorial_hours", 0) + subj.get("Taught_Practical_hours", 0)
            
            # Fallback if taught hours not available
            if main_hours == 0:
                if subj.get("Is_Split_Teaching", False) and subj.get("Co_Teachers"):
                    num_teachers = 1 + len(subj.get("Co_Teachers", []))
                    main_hours = subj.get("Total_taught_hours", subj["Total_hours"]) / num_teachers
                else:
                    main_hours = subj.get("Total_taught_hours", subj["Total_hours"])
            
            # Add to main teacher
            if main_teacher not in teacher_hours:
                teacher_hours[main_teacher] = {"total": 0, "subjects": 0, "details": []}
            
            teacher_hours[main_teacher]["total"] += main_hours
            teacher_hours[main_teacher]["subjects"] += 1
            teacher_hours[main_teacher]["details"].append({
                "subject": subj["Subject"],
                "course_sem": subj["Course_Semester"],
                "hours": main_hours,
                "split": subj.get("Is_Split_Teaching", False),
                "merged": is_merged
            })
            
            # Handle co-teachers (split teaching - they have their own hour allocation)
            # For split teaching, co-teachers should have their hours tracked separately
            # but for merged courses, they're counted together
            for co_teacher in subj.get("Co_Teachers", []):
                # For split teaching, we can't determine co-teacher hours from main subject entry
                # This needs to come from their own subject entry
                # For now, skip adding hours from co-teacher perspective
                # (they'll be counted when their own teaching entry is processed)
                if subj.get("Is_Split_Teaching", False):
                    continue
                else:
                    # Co-teaching: full hours for all
                    co_hours = main_hours
                
                if co_teacher not in teacher_hours:
                    teacher_hours[co_teacher] = {"total": 0, "subjects": 0, "details": []}

                teacher_hours[co_teacher]["total"] += co_hours
                teacher_hours[co_teacher]["subjects"] += 1
                teacher_hours[co_teacher]["details"].append({
                    "subject": subj["Subject"],
                    "course_sem": subj["Course_Semester"],
                    "hours": co_hours,
                    "split": False,  # Co-teaching is not split
                    "merged": is_merged
                })
        
        return teacher_hours
        
    def validate_config_match(self) -> bool:
        """Validate that config section counts match input Excel"""
        print("\n📋 Validating Config vs Input Consistency...")
        print("-" * 70)
        
        errors = []
        warnings = []
        
        # For DSC/DSE subjects: Check that row count matches section count
        # Logic: If course has N sections, each subject should appear N times
        
        course_subject_counts = {}  # {(course, semester, subject): count}
        
        for idx, row in self.df.iterrows():
            if pd.isna(row["Course"]) or str(row["Course"]).strip() == "":
                continue  # Skip GE/SEC/VAC/AEC
            
            course_input = str(row["Course"]).strip()
            semester = int(row["Semester"])
            subject = str(row["Subject"]).strip()
            
            # Handle course merging (e.g., "CS(H) + CA(P)")
            course_parts = [c.strip() for c in course_input.split("+")]
            
            # Validate EACH course part separately
            for course_part in course_parts:
                course = Config.get_full_course_name(course_part)
                
                key = (course, semester, subject)
                course_subject_counts[key] = course_subject_counts.get(key, 0) + 1
                
                # Check if course exists in config
                if course not in Config.COURSE_SECTIONS:
                    if (course, "not_in_sections") not in [(e[0], e[1]) for e in errors if len(e) == 2]:
                        errors.append(
                            (course, "not_in_sections",
                            f"❌ Course '{course}' (from '{course_part}') not found in config COURSE_SECTIONS")
                        )
                    continue
                
                # Check if semester exists for this course
                if semester not in Config.COURSE_SECTIONS[course]:
                    if (course, semester, "no_semester") not in [(e[0], e[1], e[2]) for e in errors if len(e) > 2]:
                        errors.append(
                            (course, semester, "no_semester",
                            f"❌ {course} Sem{semester}: Semester not configured in COURSE_SECTIONS")
                        )
                    continue
                
                # Check if student strengths are defined
                if course not in Config.COURSE_STRENGTHS:
                    if (course, "no_strengths") not in [(e[0], e[1]) for e in errors if len(e) == 2]:
                        errors.append(
                            (course, "no_strengths",
                            f"❌ {course}: Student strengths not defined in COURSE_STRENGTHS")
                        )
                    continue
                
                if semester not in Config.COURSE_STRENGTHS[course]:
                    if (course, semester, "no_sem_strengths") not in [(e[0], e[1], e[2]) for e in errors if len(e) > 2]:
                        errors.append(
                            (course, semester, "no_sem_strengths",
                            f"❌ {course} Sem{semester}: Student strengths not defined in COURSE_STRENGTHS")
                        )
        
        # Validate sections exist in config and match counts
        course_semester_sections = {}
        for idx, row in self.df.iterrows():
            if pd.isna(row["Course"]) or str(row["Course"]).strip() == "":
                continue
            
            course_input = str(row["Course"]).strip()
            semester = int(row["Semester"])
            # Handle NaN (empty) sections from pandas
            if pd.notna(row["Section"]) and str(row["Section"]).strip():
                section = str(row["Section"]).strip().upper()
            else:
                section = ""
            
            # Handle course merging
            course_parts = [c.strip() for c in course_input.split("+")]
            
            for course_part in course_parts:
                course = Config.get_full_course_name(course_part)
                
                key = (course, semester)
                if key not in course_semester_sections:
                    course_semester_sections[key] = set()
                # Only add section if it's not empty
                if section:
                    course_semester_sections[key].add(section)

        # Check if sections match config
        for (course, semester), sections_found in course_semester_sections.items():
            if course in Config.COURSE_SECTIONS and semester in Config.COURSE_SECTIONS[course]:
                expected_count = Config.COURSE_SECTIONS[course][semester]
                found_count = len(sections_found)
                
                # Skip validation if no sections found (all are single-section subjects)
                if found_count == 0:
                    continue
                
                expected_letters = set(Config.get_section_letters(expected_count))
                
                if found_count != expected_count:
                    errors.append(
                        (course, semester, "section_mismatch",
                        f"❌ {course} Sem{semester}: Found {found_count} section(s) {sorted(sections_found)} "
                        f"but config shows {expected_count} section(s) {sorted(expected_letters)}")
                    )
                elif sections_found != expected_letters:
                    warnings.append(
                        f"⚠️  {course} Sem{semester}: Section letters {sorted(sections_found)} "
                        f"don't match expected {sorted(expected_letters)}"
                    )
        
        # Check GE/SEC/VAC/AEC subjects
        for subject_type in ["GE", "SEC", "VAC", "AEC"]:
            type_rows = self.df[self.df["Subject_type"] == subject_type]
            
            for semester in type_rows["Semester"].unique():
                sem_rows = type_rows[type_rows["Semester"] == semester]
                
                for subject in sem_rows["Subject"].unique():
                    subject_rows = sem_rows[sem_rows["Subject"] == subject]
                    excel_section_count = len(subject_rows)  # Each row = 1 section for GE/SEC/VAC
                    
                    # Check if subject exists in config
                    if subject_type not in Config.GE_SEC_VAC_STRENGTHS:
                        if (subject_type, "not_configured") not in [(e[0], e[1]) for e in errors if len(e) == 2]:
                            errors.append(
                                (subject_type, "not_configured",
                                f"❌ {subject_type} subjects not configured in GE_SEC_VAC_STRENGTHS")
                            )
                        continue
                    
                    if semester not in Config.GE_SEC_VAC_STRENGTHS[subject_type]:
                        errors.append(
                            (subject_type, semester, subject,
                            f"❌ {subject_type} Sem{semester}: Not configured in GE_SEC_VAC_STRENGTHS")
                        )
                        continue
                    
                    if subject not in Config.GE_SEC_VAC_STRENGTHS[subject_type][semester]:
                        errors.append(
                            (subject_type, semester, subject,
                            f"❌ {subject_type} '{subject}' Sem{semester}: Missing from GE_SEC_VAC_STRENGTHS. "
                            f"Found {excel_section_count} section(s) in Excel, please add student strengths to config.")
                        )
                        continue
                    
                    # Check if section count matches
                    config_sections = Config.GE_SEC_VAC_STRENGTHS[subject_type][semester][subject]
                    config_section_count = len(config_sections)
                    
                    if excel_section_count != config_section_count:
                        warnings.append(
                            f"⚠️  {subject_type} '{subject}' Sem{semester}: "
                            f"Excel has {excel_section_count} section(s), config has {config_section_count}"
                        )
        
        # Display results
        if errors:
            print("\n❌ CRITICAL CONFIG MISMATCHES:")
            for error in errors:
                # Extract the message (last element)
                print(f"   {error[-1]}")
        
        if warnings:
            print("\n⚠️  CONFIG WARNINGS:")
            for warning in warnings:
                print(f"   {warning}")
        
        if not errors and not warnings:
            print("   ✅ All config entries match input Excel")
        
        print("-" * 70)
        return len(errors) == 0
    
    def get_subjects(self) -> List[Dict[str, Any]]:
        """Get list of subjects"""
        return self.subjects
    
    def get_teachers(self) -> List[str]:
        """Get unique list of teachers"""
        return list(set(subj["Teacher"] for subj in self.subjects))
    
    def get_rooms(self) -> List[str]:
        """Get unique list of room types needed"""
        rooms = {"Classroom"}  # Always need classrooms
        for subj in self.subjects:
            if subj["Lab_type"]:
                rooms.add(subj["Lab_type"])
        return list(rooms)
    
    def get_course_semesters(self) -> List[str]:
        """Get unique list of course-semester combinations"""
        return list(set(subj["Course_Semester"] for subj in self.subjects))
    
    def get_courses(self) -> List[str]:
        """Get unique list of courses"""
        courses = set(subj["Course"] for subj in self.subjects if subj["Course"] != "COMMON")
        return list(courses)
    
    def get_room_capacities(self) -> Dict[str, Dict]:
        """Get room information from config"""
        # Build room capacity summary from individual ROOMS
        room_capacities = {}
        
        # Count classrooms
        classrooms = [name for name, info in Config.ROOMS.items() if info["type"] == "classroom"]
        if classrooms:
            room_capacities["Classroom"] = {
                "count": len(classrooms),
                "rooms": classrooms
            }
        
        # Count labs by department
        labs_by_dept = {}
        for name, info in Config.ROOMS.items():
            if info["type"] == "lab":
                dept = info.get("department", "General")
                if dept not in labs_by_dept:
                    labs_by_dept[dept] = []
                labs_by_dept[dept].append(name)
        
        # Add lab counts
        for dept, lab_list in labs_by_dept.items():
            # Use department lab code from DEPARTMENT_LABS mapping
            lab_code = Config.DEPARTMENT_LABS.get(dept, f"Lab-{dept}")
            room_capacities[lab_code] = {
                "count": len(lab_list),
                "rooms": lab_list
            }
        
        return room_capacities
    
    def print_data_summary(self):
            """Print comprehensive summary of loaded data with diagnostics"""
            if not self.subjects:
                print("❌ No data loaded")
                return
            
            print("\n📊 COMPREHENSIVE DATA SUMMARY:")
            print("=" * 70)
            print(f"   Semester Type: {self.semester_type.upper()}")
            print(f"   Total subject-section combinations: {len(self.subjects)}")
            
            # Separate common and course-specific
            common_subjects = [s for s in self.subjects if s["Course"] == "COMMON"]
            course_subjects = [s for s in self.subjects if s["Course"] != "COMMON"]
            
            print(f"\n   📚 Subject Breakdown:")
            
            # Count unique common subjects (accounting for sections)
            # Note: Different sections = different classes for GE/SEC/VAC
            unique_common = set()
            for s in common_subjects:
                # Include section in key if it exists (different sections = different classes)
                if s.get("Section"):
                    key = (s["Semester"], s["Subject"], s["Subject_type"], s["Section"])
                else:
                    key = (s["Semester"], s["Subject"], s["Subject_type"])
                unique_common.add(key)
            
            # Count unique course subjects (accounting for merged courses)
            unique_course = set()
            processed_merge_groups = set()
            for s in course_subjects:
                is_merged = s.get("Is_Merged", False)
                merge_group_id = s.get("Merge_Group_ID")
                
                if is_merged and merge_group_id:
                    if merge_group_id not in processed_merge_groups:
                        unique_course.add((s["Semester"], s["Subject"]))
                        processed_merge_groups.add(merge_group_id)
                else:
                    unique_course.add((s["Course"], s["Semester"], s["Subject"], s.get("Section", "")))
            
            print(f"      Common subjects (GE/SEC/VAC/AEC): {len(unique_common)} unique")
            print(f"      Course-specific subjects: {len(unique_course)} unique")
            print(f"      Teachers: {len(self.get_teachers())}")
            
            # Teacher workload analysis
            print(f"\n   👨‍🏫 Teacher Workload Analysis:")
            teacher_hours = self._count_teacher_hours_correctly(self.subjects)
            
            overloaded = []
            for teacher, data in sorted(teacher_hours.items(), key=lambda x: x[1]["total"], reverse=True):
                rank = self.teacher_ranks.get(teacher, Config.DEFAULT_TEACHER_RANK)
                cap = Config.get_teacher_hour_cap(rank)
                status = "✅" if data["total"] <= cap else "❌"
                print(f"      {status} {teacher} ({rank.title()}): "
                      f"{data['total']:.1f}/{cap}h ({data['subjects']} subjects)")
                if data["total"] > cap:
                    overloaded.append(teacher)

            if overloaded:
                print(f"\n      ⚠️  OVERLOADED TEACHERS: {len(overloaded)}")
                print(f"         These teachers exceed their per-rank cap "
                      f"(see Config.TEACHER_RANK_HOUR_CAPS)")
            
            # Hours breakdown (accounting for merged courses)
            processed_merge_groups = set()
            total_lecture = 0
            total_tutorial = 0
            total_practical = 0
            
            for s in self.subjects:
                is_merged = s.get("Is_Merged", False)
                merge_group_id = s.get("Merge_Group_ID")
                
                if is_merged and merge_group_id in processed_merge_groups:
                    continue
                
                if is_merged and merge_group_id:
                    processed_merge_groups.add(merge_group_id)
                
                total_lecture += s["Lecture_hours"]
                total_tutorial += s["Tutorial_hours"]
                total_practical += s["Practical_hours"]
            
            print(f"\n   ⏰ Hour Requirements:")
            print(f"      Lecture hours: {total_lecture}")
            print(f"      Tutorial hours: {total_tutorial}")
            print(f"      Practical hours: {total_practical}")
            print(f"      TOTAL hours: {total_lecture + total_tutorial + total_practical}")
            
            # Subject type breakdown (count unique subjects, respecting merges)
            print(f"\n   📋 Subject Type Distribution:")
            type_counts = {}
            type_hours = {}
            processed_merge_groups = set()
            
            for subj in self.subjects:
                stype = subj["Subject_type"]
                
                # Check if merged
                is_merged = subj.get("Is_Merged", False)
                merge_group_id = subj.get("Merge_Group_ID")
                
                if is_merged and merge_group_id in processed_merge_groups:
                    continue
                
                if is_merged and merge_group_id:
                    processed_merge_groups.add(merge_group_id)
                
                type_counts[stype] = type_counts.get(stype, 0) + 1
                type_hours[stype] = type_hours.get(stype, 0) + subj["Total_hours"]
            
            for stype in sorted(type_counts.keys()):
                print(f"      {stype}: {type_counts[stype]} unique subjects, {type_hours[stype]} hours")
            
            # Room requirements
            print(f"\n   🏢 Room Requirements:")
            theory_classes = sum(1 for s in self.subjects if s["Lecture_hours"] > 0 or s["Tutorial_hours"] > 0)
            practical_classes = sum(1 for s in self.subjects if s["Practical_hours"] > 0)
            
            print(f"      Theory classes: {theory_classes} (need classrooms)")
            print(f"      Practical classes: {practical_classes} (need labs)")
            
            # Get room capacities using the instance method
            room_capacities = self.get_room_capacities()
            
            # Fixed slot analysis
            print(f"\n   🔒 Fixed Slot Subject Analysis:")
            for slot_type in ["GE", "SEC", "VAC", "AEC"]:
                subjects_of_type = [s for s in self.subjects if s["Subject_type"] == slot_type]
                if subjects_of_type:
                    total_hours = sum(s["Total_hours"] for s in subjects_of_type)
                    
                    # Get slot indices - need to aggregate across all years for SEC/VAC
                    if slot_type in ["SEC", "VAC"]:
                        # For SEC/VAC, aggregate slots from all subjects' semesters
                        all_slot_indices = set()
                        for subject in subjects_of_type:
                            semester = subject["Semester"]
                            slot_indices = Config.get_fixed_slot_indices(slot_type, semester)
                            all_slot_indices.update(slot_indices)
                        slots_available = len(all_slot_indices)
                    else:
                        # For GE/AEC, get slots directly
                        slots_available = len(Config.get_fixed_slot_indices(slot_type))
                    
                    classroom_count = room_capacities.get("Classroom", {}).get("count", 10)
                    capacity = slots_available * classroom_count
                    
                    print(f"      {slot_type}: {len(subjects_of_type)} subjects, {total_hours}h needed")
                    print(f"         Slots: {slots_available}, Capacity: {capacity} class-hours")
                    if total_hours > capacity:
                        print(f"         ❌ OVERFLOW: Need {total_hours - capacity} more hours!")
                    else:
                        print(f"         ✅ OK: {capacity - total_hours} hours spare")
            
            # Capacity estimation
            print(f"\n   📊 Capacity Estimation:")
            total_slots = len(Config.get_time_slots())
            fixed_slots = len(Config.get_all_fixed_slot_indices())
            available_slots = total_slots - fixed_slots
            
            classroom_count = room_capacities.get("Classroom", {}).get("count", 10)
            classroom_capacity = available_slots * classroom_count
            
            theory_hours = total_lecture + total_tutorial
            
            print(f"      Total time slots: {total_slots} (6 days × 9 hours)")
            print(f"      Fixed slots reserved: {fixed_slots}")
            print(f"      Available for DSC/DSE: {available_slots}")
            print(f"      Classroom capacity: {classroom_capacity} class-hours ({classroom_count} rooms)")
            print(f"      Theory hours needed: {theory_hours}")
            print(f"      Theory utilization: {(theory_hours/classroom_capacity*100):.1f}%")
            
            if theory_hours > classroom_capacity:
                print(f"      ❌ INSUFFICIENT CAPACITY: Need {theory_hours - classroom_capacity} more class-hours")
            elif theory_hours / classroom_capacity > 0.9:
                print(f"      ⚠️  HIGH UTILIZATION: Near capacity")
            else:
                print(f"      ✅ SUFFICIENT CAPACITY: {classroom_capacity - theory_hours} class-hours spare")
            
            print("=" * 70)