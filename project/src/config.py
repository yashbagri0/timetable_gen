"""
Configuration settings for the timetable generator
"""
from typing import List, Dict

class Config:
    # Time slots configuration
    DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    START_HOUR = 8
    END_HOUR = 17
    
    @classmethod
    def get_time_slots(cls):
        slots = [f"{h}:30-{h+1}:30" for h in range(cls.START_HOUR, cls.END_HOUR)]
        return [(d, s) for d in cls.DAYS for s in slots]
    
    @classmethod
    def get_slots_list(cls):
        return [f"{h}:30-{h+1}:30" for h in range(cls.START_HOUR, cls.END_HOUR)]
    
    # Valid semester types
    ODD_SEMESTERS = [1, 3, 5, 7]
    EVEN_SEMESTERS = [2, 4, 6, 8]
    
    # Valid subject types
    SUBJECT_TYPES = ["DSC", "DSE", "GE", "SEC", "VAC", "AEC"]
    
    # Subject types with fixed slots
    FIXED_SLOT_TYPES = ["GE", "SEC", "VAC", "AEC"]
    
    # Predefined subject hour requirements (ACTUAL HOURS)
    # Format: {"Le": lectures, "Tu": tutorials, "Pr": practicals (in actual hours)}
    SUBJECT_REQUIREMENTS = {
        "DSC": {
            "theory_only": {"Le": 3, "Tu": 1, "Pr": 0},  # (3,1,0) - 4 credits
            "with_lab": {"Le": 3, "Tu": 0, "Pr": 2}      # (3,0,2) - 4 credits, (2 labs = 1 credit)
        },
        "DSE": {
            "theory_only": {"Le": 3, "Tu": 1, "Pr": 0},
            "with_lab": {"Le": 3, "Tu": 0, "Pr": 2}
        },
        "GE": {
            "theory_only": {"Le": 3, "Tu": 1, "Pr": 0},
            "with_lab": {"Le": 3, "Tu": 0, "Pr": 2}
        },
        "SEC": {
            "theory_only": {"Le": 2, "Tu": 0, "Pr": 0},  # (2,0,0) - 2 credits
            "with_lab": {"Le": 0, "Tu": 0, "Pr": 4}      # (0,0,4) - 2 credits, (4 labs = 2 credits)
        },
        "VAC": {
            "theory_only": {"Le": 2, "Tu": 0, "Pr": 0},
            "with_lab": {"Le": 0, "Tu": 0, "Pr": 4}
        },
        "AEC": {
            "theory_only": {"Le": 2, "Tu": 0, "Pr": 0},
            "with_lab": {"Le": 0, "Tu": 0, "Pr": 4}
        }
    }
    
    # Subject types by year
    YEAR1_SUBJECTS = ["DSC", "GE", "SEC", "VAC", "AEC"]
    YEAR2_SUBJECTS = ["DSC", "DSE", "GE", "SEC", "VAC", "AEC"]
    YEAR3_SUBJECTS = ["DSC", "DSE", "GE", "SEC"]
    YEAR4_SUBJECTS = ["DSC", "DSE", "GE"]
    
    @classmethod
    def get_allowed_subject_types_for_semester(cls, semester: int) -> List[str]:
        if semester in [1, 2]:
            return cls.YEAR1_SUBJECTS
        elif semester in [3, 4]:
            return cls.YEAR2_SUBJECTS
        elif semester in [5, 6]:
            return cls.YEAR3_SUBJECTS
        elif semester in [7, 8]:
            return cls.YEAR4_SUBJECTS
        return []
    
    @classmethod
    def get_fixed_slot_types_for_semester(cls, semester: int) -> List[str]:
        allowed_types = cls.get_allowed_subject_types_for_semester(semester)
        return [t for t in cls.FIXED_SLOT_TYPES if t in allowed_types]
    
    # YEAR-SPECIFIC Fixed slot configurations
    FIXED_SLOTS = {
        "GE": {
            "slots": ["12:30-13:30"],
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            "description": "Generic Electives Lectures (Mon-Fri 12:30-1:30)"
        },
        "GE_LAB_YEAR1": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Sat"],
            "description": "GE Labs Year 1 (Saturday 3:30-5:30)"
        },
        "GE_LAB_YEAR2": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Wed"],
            "description": "GE Labs Year 2 (Wednesday 3:30-5:30)"
        },
        "GE_LAB_YEAR3": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Thu"],
            "description": "GE Labs Year 3 (Thursday 3:30-5:30)"
        },
        "GE_LAB_YEAR4": {
            "slots": ["10:30-11:30", "11:30-12:30"],
            "days": ["Tue"],
            "description": "GE Labs Year 4 (Tuesday 10:30-12:30)"
        },
        "SEC_YEAR1": {
            "slots": ["13:30-14:30", "14:30-15:30"],
            "days": ["Fri"],
            "description": "SEC Year 1 (Friday 1:30-3:30)"
        },
        "SEC_YEAR1_SAT": {
            "slots": ["8:30-9:30", "9:30-10:30"],
            "days": ["Sat"],
            "description": "SEC Year 1 (Saturday 8:30-10:30)"
        },
        "SEC_YEAR2": {
            "slots": ["13:30-14:30", "14:30-15:30"],
            "days": ["Fri"],
            "description": "SEC Year 2 (Friday 1:30-3:30)"
        },
        "SEC_YEAR2_SAT": {
            "slots": ["8:30-9:30", "9:30-10:30"],
            "days": ["Sat"],
            "description": "SEC Year 2 (Saturday 8:30-10:30)"
        },
        "SEC_YEAR3": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Mon", "Tue"],
            "description": "SEC Year 3 (Monday & Tuesday 3:30-5:30)"
        },
        "VAC_YEAR1": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Fri"],
            "description": "VAC Year 1 (Friday 3:30-5:30)"
        },
        "VAC_YEAR1_SAT": {
            "slots": ["10:30-11:30", "11:30-12:30"],
            "days": ["Sat"],
            "description": "VAC Year 1 (Saturday 10:30-12:30)"
        },
        "VAC_YEAR2": {
            "slots": ["15:30-16:30", "16:30-17:30"],
            "days": ["Fri"],
            "description": "VAC Year 2 (Friday 3:30-5:30)"
        },
        "VAC_YEAR2_SAT": {
            "slots": ["10:30-11:30", "11:30-12:30"],
            "days": ["Sat"],
            "description": "VAC Year 2 (Saturday 10:30-12:30)"
        },
        "AEC": {
            "slots": ["12:30-13:30"],
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "description": "Ability Enhancement Courses (Mon-Fri 12:30-1:30)"
        },
        "AEC_SAT": {
            "slots": ["13:30-14:30", "14:30-15:30"],
            "days": ["Sat"],
            "description": "Ability Enhancement Courses (Saturday 1:30-3:30)"
        }
    }
    
    # Course sections configuration
    COURSE_SECTIONS = {
        "B.Sc. (Hons.) Chemistry": {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 1, 8: 1},
        "B.Sc. (Hons) Computer Science": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Sc. (Hons) Electronics": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Sc. (Hons.) Mathematics": {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2},
        "B.Sc. (Hons.) Physics": {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2},
        "B.Sc. Physical science Industrial Chemistry": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Sc. Physical Science Chemistry": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Sc. Physical Science Electronics": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Sc. Physical Science Computer Science": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.A. (Hons.) Economics": {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2},
        "B.A. (Hons.) English": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.A. (Hons.) Hindi": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.A. (Hons.) History": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.A. (Hons.) Political Science": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.A. Program": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1},
        "B.Com (Hons)": {1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3, 7: 3, 8: 3},
        "B.Com": {1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3, 7: 3, 8: 3},
    }
    
    # Course short form mappings
    COURSE_SHORT_FORMS = {
        "CS(H)": "B.Sc. (Hons) Computer Science",
        "CS(P)": "B.Sc. Physical Science Computer Science",
        "Chem(H)": "B.Sc. (Hons.) Chemistry",
        "Chem(P)": "B.Sc. Physical Science Chemistry",
        "IC(P)": "B.Sc. Physical science Industrial Chemistry",
        "Elec(H)": "B.Sc. (Hons) Electronics",
        "Elec(P)": "B.Sc. Physical Science Electronics",
        "Math(H)": "B.Sc. (Hons.) Mathematics",
        "Phy(H)": "B.Sc. (Hons.) Physics",
        "Eco(H)": "B.A. (Hons.) Economics",
        "Eng(H)": "B.A. (Hons.) English",
        "Hin(H)": "B.A. (Hons.) Hindi",
        "His(H)": "B.A. (Hons.) History",
        "PolSci(H)": "B.A. (Hons.) Political Science",
        "CA(P)": "B.A. Program",
        "BCom(H)": "B.Com (Hons)",
        "BCom": "B.Com"
    }

    # Reverse mapping (full name -> short form)
    COURSE_FULL_TO_SHORT = {v: k for k, v in COURSE_SHORT_FORMS.items()}

    @classmethod
    def get_full_course_name(cls, short_form: str) -> str:
        """Convert short form to full course name"""
        return cls.COURSE_SHORT_FORMS.get(short_form, short_form)

    @classmethod
    def get_short_course_name(cls, full_name: str) -> str:
        """Convert full course name to short form"""
        return cls.COURSE_FULL_TO_SHORT.get(full_name, full_name)
    
    # Student strengths per course-section (EDIT THESE WITH REAL DATA)
    COURSE_STRENGTHS = {
        "B.Sc. (Hons.) Chemistry": {
            1: {"A": 60, "B": 58}, 2: {"A": 58, "B": 56},
            3: {"A": 56, "B": 54}, 4: {"A": 54, "B": 52},
            5: {"A": 52, "B": 50}, 6: {"A": 50, "B": 48},
            7: {"A": 45}, 8: {"A": 43}
        },
        "B.Sc. (Hons) Computer Science": {
            1: {"A": 55}, 2: {"A": 53}, 3: {"A": 51}, 4: {"A": 49},
            5: {"A": 47}, 6: {"A": 45}, 7: {"A": 10}, 8: {"A": 30}
        },
        "B.Sc. (Hons) Electronics": {
            1: {"A": 50}, 2: {"A": 48}, 3: {"A": 46}, 4: {"A": 44},
            5: {"A": 42}, 6: {"A": 40}, 7: {"A": 38}, 8: {"A": 36}
        },
        "B.Sc. (Hons.) Mathematics": {
            1: {"A": 55, "B": 53}, 2: {"A": 53, "B": 51},
            3: {"A": 51, "B": 49}, 4: {"A": 49, "B": 47},
            5: {"A": 47, "B": 45}, 6: {"A": 45, "B": 43},
            7: {"A": 43, "B": 41}, 8: {"A": 41, "B": 39}
        },
        "B.Sc. (Hons.) Physics": {
            1: {"A": 58, "B": 56}, 2: {"A": 56, "B": 54},
            3: {"A": 54, "B": 52}, 4: {"A": 52, "B": 50},
            5: {"A": 50, "B": 48}, 6: {"A": 48, "B": 46},
            7: {"A": 46, "B": 44}, 8: {"A": 44, "B": 42}
        },
        "B.Sc. Physical science Industrial Chemistry": {
            1: {"A": 45}, 2: {"A": 43}, 3: {"A": 41}, 4: {"A": 39},
            5: {"A": 37}, 6: {"A": 35}, 7: {"A": 33}, 8: {"A": 31}
        },
        "B.Sc. Physical Science Chemistry": {
            1: {"A": 48}, 2: {"A": 46}, 3: {"A": 44}, 4: {"A": 42},
            5: {"A": 40}, 6: {"A": 38}, 7: {"A": 36}, 8: {"A": 34}
        },
        "B.Sc. Physical Science Electronics": {
            1: {"A": 42}, 2: {"A": 40}, 3: {"A": 38}, 4: {"A": 36},
            5: {"A": 34}, 6: {"A": 32}, 7: {"A": 30}, 8: {"A": 28}
        },
        "B.Sc. Physical Science Computer Science": {
            1: {"A": 50}, 2: {"A": 48}, 3: {"A": 46}, 4: {"A": 44},
            5: {"A": 42}, 6: {"A": 40}, 7: {"A": 38}, 8: {"A": 36}
        },
        "B.A. (Hons.) Economics": {
            1: {"A": 60, "B": 58}, 2: {"A": 58, "B": 56},
            3: {"A": 56, "B": 54}, 4: {"A": 54, "B": 52},
            5: {"A": 52, "B": 50}, 6: {"A": 50, "B": 48},
            7: {"A": 48, "B": 46}, 8: {"A": 46, "B": 44}
        },
        "B.A. (Hons.) English": {
            1: {"A": 45}, 2: {"A": 43}, 3: {"A": 41}, 4: {"A": 39},
            5: {"A": 37}, 6: {"A": 35}, 7: {"A": 33}, 8: {"A": 31}
        },
        "B.A. (Hons.) Hindi": {
            1: {"A": 40}, 2: {"A": 38}, 3: {"A": 36}, 4: {"A": 34},
            5: {"A": 32}, 6: {"A": 30}, 7: {"A": 28}, 8: {"A": 26}
        },
        "B.A. (Hons.) History": {
            1: {"A": 42}, 2: {"A": 40}, 3: {"A": 38}, 4: {"A": 36},
            5: {"A": 34}, 6: {"A": 32}, 7: {"A": 30}, 8: {"A": 28}
        },
        "B.A. (Hons.) Political Science": {
            1: {"A": 48}, 2: {"A": 46}, 3: {"A": 44}, 4: {"A": 42},
            5: {"A": 40}, 6: {"A": 38}, 7: {"A": 36}, 8: {"A": 34}
        },
        "B.A. Program": {
            1: {"A": 50}, 2: {"A": 48}, 3: {"A": 46}, 4: {"A": 44},
            5: {"A": 42}, 6: {"A": 40}, 7: {"A": 10}, 8: {"A": 36}
        },
        "B.Com (Hons)": {
            1: {"A": 65, "B": 63, "C": 61}, 2: {"A": 63, "B": 61, "C": 59},
            3: {"A": 61, "B": 59, "C": 57}, 4: {"A": 59, "B": 57, "C": 55},
            5: {"A": 57, "B": 55, "C": 53}, 6: {"A": 55, "B": 53, "C": 51},
            7: {"A": 53, "B": 51, "C": 49}, 8: {"A": 51, "B": 49, "C": 47}
        },
        "B.Com": {
            1: {"A": 60, "B": 58, "C": 56}, 2: {"A": 58, "B": 56, "C": 54},
            3: {"A": 56, "B": 54, "C": 52}, 4: {"A": 54, "B": 52, "C": 50},
            5: {"A": 52, "B": 50, "C": 48}, 6: {"A": 50, "B": 48, "C": 46},
            7: {"A": 48, "B": 46, "C": 44}, 8: {"A": 46, "B": 44, "C": 42}
        }
    }
    
    # GE/SEC/VAC strengths (EDIT WITH REAL DATA WHEN AVAILABLE)
    GE_SEC_VAC_STRENGTHS = {
        "GE": {
            1: {
                "Programming using C++": {"A": 30, "B": 30},
            },
            3: {
                "Database Management System": {"A": 30, "B": 30},
            },
            5: {
                "Operating System": {"A": 50}
            },
            7: {
                "Design and Analysis of Algo": {"A": 48}
            }
        },
        "SEC": {
            1: {
                "IT Skills and Data Analysis 1": {"A": 30}
            },
            3: {
                "IT Skills and Data Analysis 1": {"A": 70}
            },
            5: {
                "Latex Type setting for Beginners": {"A": 60}
            }
        },
        "VAC": {
            1: {
                "Digital Empowerment": {"A": 50}
            },
            3: {
                "Emotional Intelligence": {"A": 48}
            }
        },
        "AEC": {}  # Placeholder
    }
    
    @classmethod
    def get_section_letters(cls, num_sections):
        return [chr(65 + i) for i in range(num_sections)]
    
    # Department-to-Lab mapping
    DEPARTMENT_LABS = {
        "Computer Science": "CL",
        "Physics": "PL",
        "Chemistry": "ChemL",
        "Biology": "BioL",
        "Electronics": "EL"
    }
    
    # INDIVIDUAL ROOM CONFIGURATIONS (60 classrooms + labs)
    ROOMS = {
        # Classrooms: 60 total
        # Ground Floor: 15 rooms (60-80 capacity)
        **{f"R-{i}": {
            "type": "classroom",
            "capacity_min": 60,
            "capacity_max": 80,
            "floor": 0,
            "department": "COMMON"
        } for i in range(1, 16)},
        
        # First Floor: 30 rooms (mixed capacity)
        # 15 large (60-80)
        **{f"R-{i}": {
            "type": "classroom",
            "capacity_min": 60,
            "capacity_max": 80,
            "floor": 1,
            "department": "COMMON"
        } for i in range(16, 31)},
        # 15 medium (40-50)
        **{f"R-{i}": {
            "type": "classroom",
            "capacity_min": 40,
            "capacity_max": 50,
            "floor": 1,
            "department": "COMMON"
        } for i in range(31, 46)},
        
        # Second Floor: 15 rooms (mixed capacity)
        # 5 medium (40-50)
        **{f"R-{i}": {
            "type": "classroom",
            "capacity_min": 40,
            "capacity_max": 50,
            "floor": 2,
            "department": "COMMON"
        } for i in range(46, 51)},
        # 10 small (20-30)
        **{f"R-{i}": {
            "type": "classroom",
            "capacity_min": 20,
            "capacity_max": 30,
            "floor": 2,
            "department": "COMMON"
        } for i in range(51, 61)},
        
        # Computer Science Labs
        "CL-1": {
            "type": "lab",
            "capacity_min": 37,
            "capacity_max": 43,
            "floor": 1,
            "department": "Computer Science"
        },
        "CL-2": {
            "type": "lab",
            "capacity_min": 37,
            "capacity_max": 43,
            "floor": 1,
            "department": "Computer Science"
        },
        "CL-3": {
            "type": "lab",
            "capacity_min": 37,
            "capacity_max": 43,
            "floor": 1,
            "department": "Computer Science"
        },
        "CL-4": {
            "type": "lab",
            "capacity_min": 37,
            "capacity_max": 43,
            "floor": 1,
            "department": "Computer Science"
        },

        # Physics Labs
        "PL-1": {
            "type": "lab",
            "capacity_min": 22,
            "capacity_max": 28,
            "floor": 1,
            "department": "Physics"
        },
        "PL-2": {
            "type": "lab",
            "capacity_min": 27,
            "capacity_max": 33,
            "floor": 1,
            "department": "Physics"
        },

        # Chemistry Labs
        "ChemL-1": {
            "type": "lab",
            "capacity_min": 22,
            "capacity_max": 28,
            "floor": 1,
            "department": "Chemistry"
        },
        "ChemL-2": {
            "type": "lab",
            "capacity_min": 27,
            "capacity_max": 33,
            "floor": 1,
            "department": "Chemistry"
        },

        # Biology Labs
        "BioL-1": {
            "type": "lab",
            "capacity_min": 22,
            "capacity_max": 28,
            "floor": 1,
            "department": "Biology"
        },
        "BioL-2": {
            "type": "lab",
            "capacity_min": 22,
            "capacity_max": 28,
            "floor": 1,
            "department": "Biology"
        },

        # Electronics Labs
        "EL-1": {
            "type": "lab",
            "capacity_min": 22,
            "capacity_max": 28,
            "floor": 1,
            "department": "Electronics"
        },
        "EL-2": {
            "type": "lab",
            "capacity_min": 27,
            "capacity_max": 33,
            "floor": 1,
            "department": "Electronics"
        }
    }
    
    # Penalty weights for room assignment (CONFIGURABLE)
    PENALTY_WEIGHTS = {
    "oversized_room": 10,         # Room bigger than needed (wasted space)
    "undersized_room": 100,       # Room smaller than needed (cramped)
    "room_mismatch": 5,           # Minor mismatch within tolerance
    "isolated_practical": 50,     # Penalty per isolated practical hour
    "ge_lecture_slot_usage": 30,  # Penalty per hour for GE practical using lecture slots
    "theory_in_lab": 100,         # Penalty for using labs for theory classes
    }

    # Upper bound for room-penalty IntVars. Must be >= max possible overflow * weight.
    # Worst realistic case: ~200 students in a 20-capacity room => overflow 180 * 100 = 18000.
    # 1_000_000 leaves a wide safety margin without hurting solver performance.
    PENALTY_VAR_MAX = 1_000_000

    # Soft-constraint weights for teacher time preferences. Tuned to sit above
    # the routine soft constraints (theory_in_lab=100, isolated_practical=50,
    # ge_lecture_slot_usage=30, day_idx*18 early-completion) so they actually
    # shift scheduling, but well below worst-case undersized_room penalties
    # (overflow * 100 = thousands) so a real room-fit conflict still wins and
    # preferences NEVER cause INFEASIBLE. Adjust here, not in builder code.
    TEACHER_PREF_WEIGHTS = {
        "off_day":             200,   # per scheduled hour on a teacher's preferred-off day
        "avoid_time":          150,   # per scheduled hour in their avoid-time window
        "preferred_time_bonus": 50,   # subtracted per scheduled hour in their preferred window
    }

    # Per-day slot-index ranges for preference time labels. Indices are
    # offsets within a day (0..len(slots)-1), keyed off the existing time grid.
    PREFERRED_TIME_SLOTS = {
        "Morning":   [0, 1, 2],         # 8:30 – 11:30
        "Afternoon": [3, 4, 5, 6],      # 11:30 – 15:30
        "Evening":   [7, 8],            # 15:30 – 17:30
    }

    # Day-name normalization (case-insensitive); both short and long forms accepted.
    DAY_NAME_TO_INDEX = {
        "mon": 0, "monday": 0,
        "tue": 1, "tues": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
    }

    
    # Teacher-student ratio for labs (1 teacher per X students)
    LAB_TEACHER_RATIO = 20
    
    # Per-rank teaching-hour caps. Replaces the former single
    # MAX_HOURS_PER_TEACHER constant — every consumer must look up the cap
    # for the teacher's specific rank via get_teacher_hour_cap().
    TEACHER_RANK_HOUR_CAPS = {
        "assistant": 16,
        "associate": 16,
        "professor": 16,
    }
    DEFAULT_TEACHER_RANK = "assistant"

    SOLVER_TIME_LIMIT = 300
    
    # PDF settings
    PDF_FONT_SIZE = 6
    PDF_HEADER_COLOR = (0.4, 0.4, 0.4)
    PDF_ALT_ROW_COLOR = (0.9, 0.9, 0.9)
    
    # User-configurable constraints
    USER_CONFIGURABLE_CONSTRAINTS = {
        "practical_consecutive": "Ensure practical sessions occupy consecutive 2-hour slots",
        "max_consecutive_classes": "Limit maximum consecutive classes for students and teachers",
        "max_daily_hours": "Limit maximum hours per day for students (default: 6 hours)",
        "max_daily_teacher_hours": "Limit maximum teaching hours per day for teachers (default: 5-6 hours)",
        "early_completion": "Soft constraint to end classes as early as possible"
    }
    
    # Core constraints
    CORE_CONSTRAINTS = [
        "teacher_clash",
        "room_clash", 
        "course_semester_clash",
        "teacher_load",
        "hour_requirements",
        "fixed_slots"
    ]
        
    @classmethod
    def get_year_from_semester(cls, semester: int) -> int:
        if semester in [1, 2]:
            return 1
        elif semester in [3, 4]:
            return 2
        elif semester in [5, 6]:
            return 3
        elif semester in [7, 8]:
            return 4
        return 0
    
    @classmethod
    def get_fixed_slot_indices(cls, course_type: str, semester: int = None):
        time_slots = cls.get_time_slots()
        indices = []
        
        if course_type == "GE":
            if "GE" in cls.FIXED_SLOTS:
                config = cls.FIXED_SLOTS["GE"]
                for i, (day, slot) in enumerate(time_slots):
                    if day in config["days"] and slot in config["slots"]:
                        indices.append(i)
        
        elif course_type == "GE_LAB" and semester is not None:
            year = cls.get_year_from_semester(semester)
            config_key = f"GE_LAB_YEAR{year}"
            if config_key in cls.FIXED_SLOTS:
                config = cls.FIXED_SLOTS[config_key]
                for i, (day, slot) in enumerate(time_slots):
                    if day in config["days"] and slot in config["slots"]:
                        indices.append(i)
        
        elif course_type == "SEC" and semester is not None:
            year = cls.get_year_from_semester(semester)
            if year in [1, 2]:
                for config_key in [f"SEC_YEAR{year}", f"SEC_YEAR{year}_SAT"]:
                    if config_key in cls.FIXED_SLOTS:
                        config = cls.FIXED_SLOTS[config_key]
                        for i, (day, slot) in enumerate(time_slots):
                            if day in config["days"] and slot in config["slots"]:
                                indices.append(i)
            elif year == 3:
                if "SEC_YEAR3" in cls.FIXED_SLOTS:
                    config = cls.FIXED_SLOTS["SEC_YEAR3"]
                    for i, (day, slot) in enumerate(time_slots):
                        if day in config["days"] and slot in config["slots"]:
                            indices.append(i)
        
        elif course_type == "VAC" and semester is not None:
            year = cls.get_year_from_semester(semester)
            if year in [1, 2]:
                for config_key in [f"VAC_YEAR{year}", f"VAC_YEAR{year}_SAT"]:
                    if config_key in cls.FIXED_SLOTS:
                        config = cls.FIXED_SLOTS[config_key]
                        for i, (day, slot) in enumerate(time_slots):
                            if day in config["days"] and slot in config["slots"]:
                                indices.append(i)
        
        elif course_type == "AEC":
            for config_key in ["AEC", "AEC_SAT"]:
                if config_key in cls.FIXED_SLOTS:
                    config = cls.FIXED_SLOTS[config_key]
                    for i, (day, slot) in enumerate(time_slots):
                        if day in config["days"] and slot in config["slots"]:
                            indices.append(i)
        
        return indices
    
    @classmethod
    def get_all_fixed_slot_indices(cls):
        all_indices = set()
        all_indices.update(cls.get_fixed_slot_indices("GE"))
        for year in [1, 2, 3, 4]:
            semester = year * 2 - 1
            all_indices.update(cls.get_fixed_slot_indices("GE_LAB", semester))
        for year in [1, 2, 3]:
            semester = year * 2 - 1
            all_indices.update(cls.get_fixed_slot_indices("SEC", semester))
        for year in [1, 2]:
            semester = year * 2 - 1
            all_indices.update(cls.get_fixed_slot_indices("VAC", semester))
        all_indices.update(cls.get_fixed_slot_indices("AEC"))
        return list(all_indices)
    
    @classmethod
    def get_student_strength(cls, course: str, semester: int, section: str) -> int:
        """Get student strength for a course-semester-section"""
        if course == "COMMON":
            return 30  # Default for GE/SEC/VAC
        if course in cls.COURSE_STRENGTHS:
            if semester in cls.COURSE_STRENGTHS[course]:
                if section in cls.COURSE_STRENGTHS[course][semester]:
                    return cls.COURSE_STRENGTHS[course][semester][section]
        return 20  # Default fallback
    
    @classmethod
    def get_ge_sec_vac_strength(cls, subject_type: str, semester: int, subject_name: str, section: str) -> int:
        """Get student strength for GE/SEC/VAC subjects"""
        if subject_type in cls.GE_SEC_VAC_STRENGTHS:
            if semester in cls.GE_SEC_VAC_STRENGTHS[subject_type]:
                if subject_name in cls.GE_SEC_VAC_STRENGTHS[subject_type][semester]:
                    if section in cls.GE_SEC_VAC_STRENGTHS[subject_type][semester][subject_name]:
                        return cls.GE_SEC_VAC_STRENGTHS[subject_type][semester][subject_name][section]
        return 50  # Default
    
    @classmethod
    def get_rooms_by_type(cls, room_type: str) -> list:
        """Get all rooms of a specific type"""
        return [name for name, info in cls.ROOMS.items() if info["type"] == room_type]
    
    @classmethod
    def get_labs_by_department(cls, department: str) -> list:
        """Get all labs for a specific department"""
        return [name for name, info in cls.ROOMS.items()
                if info["type"] == "lab" and info.get("department") == department]

    @classmethod
    def get_teacher_hour_cap(cls, rank: str) -> int:
        """
        Resolve a teacher's weekly hour cap by rank. Rank is normalized to
        lowercase; unknown ranks raise ValueError so callers don't silently
        drop a cap when data drifts.
        """
        normalized = (rank or "").strip().lower()
        if normalized not in cls.TEACHER_RANK_HOUR_CAPS:
            raise ValueError(
                f"Unknown teacher rank '{rank}'. "
                f"Allowed: {list(cls.TEACHER_RANK_HOUR_CAPS.keys())}"
            )
        return cls.TEACHER_RANK_HOUR_CAPS[normalized]
        
    @classmethod
    def get_subject_requirement(cls, subject_type: str, has_lab: bool) -> Dict[str, int]:
        """Get predefined hour requirements for a subject type"""
        if subject_type not in cls.SUBJECT_REQUIREMENTS:
            raise ValueError(f"❌ Unknown subject type '{subject_type}' found in data")
        
        req_key = "with_lab" if has_lab else "theory_only"
        return cls.SUBJECT_REQUIREMENTS[subject_type][req_key]

    @classmethod
    def calculate_remaining_hours(cls, subject_type: str, has_lab: bool, 
                                taught_le: int, taught_tu: int, taught_pr: int) -> Dict[str, int]:
        """Calculate remaining hours needed for a subject"""
        requirement = cls.get_subject_requirement(subject_type, has_lab)
        
        remaining = {
            "Le": requirement["Le"] - taught_le,
            "Tu": requirement["Tu"] - taught_tu,
            "Pr": requirement["Pr"] - taught_pr
        }
        
        # Ensure no negative values
        remaining = {k: max(0, v) for k, v in remaining.items()}
        
        return remaining