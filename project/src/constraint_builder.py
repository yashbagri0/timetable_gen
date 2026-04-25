"""
Constraint building module - With all optimizations, efficient 
variable creation, and proper 2-hour block tracking
"""
from ortools.sat.python import cp_model
from src.config import Config
from typing import List, Dict, Any, Tuple, Set
import pandas as pd
from pprint import pprint

class ConstraintBuilder: 
    def __init__(self, subjects: List[Dict], teachers: List[str], rooms: List[str], 
                 course_semesters: List[str], room_capacities: Dict[str, Dict],
                 constraint_selector,  # ConfigAdapter from main.py
                 teacher_initials: Dict[str, str]):
        self.subjects = subjects
        self.teachers = teachers
        self.rooms = rooms
        self.course_semesters = course_semesters
        self.room_capacities = room_capacities
        self.constraint_selector = constraint_selector
        self.teacher_initials = teacher_initials
        self.time_slots = Config.get_time_slots()
        self.slots = Config.get_slots_list()
        
    def build_model(self) -> Tuple[cp_model.CpModel, Dict]:
        """
        Build the complete OR-Tools CP-SAT optimization model.
         
        Returns:
            Tuple of (model, variables dictionary)
        """
        model = cp_model.CpModel()
        
        print("\n🔧 Building optimization model...")
        
        # Create decision variables (only for allowed slots)
        variables = self._create_variables(model)
        
        # CORE CONSTRAINTS (always enabled)
        print("   ✅ Adding core constraints...")
        self._add_hour_requirements(model, variables)
        self._add_room_assignment_constraints(model, variables)
        self._add_theory_can_use_labs(model, variables)
        self._add_teacher_clash(model, variables)
        self._add_room_clash(model, variables)
        self._add_course_semester_clash(model, variables)
        self._add_teacher_load(model, variables)
        self._add_same_subject_no_concurrency(model, variables)
        self._add_merged_course_synchronization(model, variables)
        self._add_split_teaching_no_concurrency(model, variables)
        
        # OPTIONAL CONSTRAINTS (user-configured)
        if self.constraint_selector.is_enabled("practical_consecutive"):
            print(f"   ✅ Adding practical consecutive slot constraints (with 2-hour block tracking)")
            self._add_practical_consecutive(model, variables)
        
        if self.constraint_selector.is_enabled("max_consecutive_classes"):
            print(f"   ✅ Adding max consecutive classes constraint ({self.constraint_selector.get_max_consecutive_hours()}h)")
            self._add_max_consecutive_classes(model, variables)
        
        if self.constraint_selector.is_enabled("max_daily_hours"):
            print(f"   ✅ Adding max daily hours for students ({self.constraint_selector.get_max_daily_hours_students()}h)")
            self._add_max_daily_hours_students(model, variables)
        
        if self.constraint_selector.is_enabled("max_daily_teacher_hours"):
            print(f"   ✅ Adding max daily hours for teachers ({self.constraint_selector.get_max_daily_hours_teachers()}h)")
            self._add_max_daily_hours_teachers(model, variables)
        
        # OBJECTIVE FUNCTION
        self._add_objective_function(model, variables)
        
        print("✅ Model built successfully")
        return model, variables
    
    def _build_subject_id(self, subj: Dict) -> str:
        """
        Build consistent subject_id, handling split teaching with teacher initials.
        
        Args:
            subj: Subject dictionary
            
        Returns:
            Unique subject identifier string
        """
        if subj.get("Is_Split_Teaching", False):
            teacher_initials = self.teacher_initials.get(subj["Teacher"], "UNK")
            return f"{subj['Course_Semester']}_{subj['Subject']}_{teacher_initials}"
        else:
            return f"{subj['Course_Semester']}_{subj['Subject']}"
        
    def _get_event_id(self, subj: Dict) -> str:
        """
        Returns the scheduling event ID.
        Merged courses share ONE event_id.
        """
        if subj.get("Merge_Group_ID"):
            return f"MERGE_{subj['Merge_Group_ID']}"
        else:
            return self._build_subject_id(subj)
    
    def _get_allowed_slots_for_subject(self, subj: Dict) -> Set[int]:
        """
        Calculate which time slots are allowed for this subject based on type.
        This ensures we only create variables for slots where scheduling is possible.
        
        Args:
            subj: Subject dictionary
            
        Returns:
            Set of allowed time slot indices
        """
        subject_type = subj["Subject_type"]
        semester = subj["Semester"]
        all_slots = set(range(len(self.time_slots))) # Mon 8:30-9:30 is 0,...., Sat 16:30-17:30 is 53

        # Get semester-specific fixed slot types
        semester_fixed_types = Config.get_fixed_slot_types_for_semester(semester)
        
        if subject_type in Config.FIXED_SLOT_TYPES:
            # Fixed slot subjects (GE/SEC/VAC/AEC) - ONLY their specific slots
            if subject_type == "GE":
                # GE lectures/tutorials: only GE lecture slots
                return set(Config.get_fixed_slot_indices("GE")) # {4, 13, 22, 31, 40, 49}, all 12:30-13:30 slots
            
            elif subject_type in ["SEC", "VAC"]:
                # SEC/VAC: their year-specific slots
                return set(Config.get_fixed_slot_indices(subject_type, semester))
            
            elif subject_type == "AEC":
                # AEC: AEC slots (all semesters)
                aec_slots = set(Config.get_fixed_slot_indices("AEC"))
                aec_sat_slots = set(Config.get_fixed_slot_indices("AEC_SAT")) if "AEC_SAT" in Config.FIXED_SLOTS else set()
                return aec_slots.union(aec_sat_slots)
        
        else:
            # DSC/DSE subjects - ALL slots EXCEPT fixed slots
            blocked_slots = set()
            
            # Block all fixed slot types available in this semester
            for fixed_type in semester_fixed_types:
                blocked_slots.update(Config.get_fixed_slot_indices(fixed_type, semester))
            
            # Also block GE_LAB slots for that particular year
            semester = subj["Semester"]
            ge_lab_slots = Config.get_fixed_slot_indices("GE_LAB", semester)
            blocked_slots.update(ge_lab_slots)
            
            return all_slots - blocked_slots
    
    def _get_allowed_slots_for_ge_practical(self, semester: int) -> Set[int]:
        """
        Get allowed slots for GE Lab practicals (can use GE_LAB or regular GE slots).
        
        Args:
            semester: Semester number
            
        Returns:
            Set of allowed time slot indices
        """
        ge_lecture_slots = set(Config.get_fixed_slot_indices("GE"))
        ge_lab_slots = set(Config.get_fixed_slot_indices("GE_LAB", semester))
        
        return ge_lecture_slots.union(ge_lab_slots)
    
    def _create_variables(self, model: cp_model.CpModel) -> Dict:
        """
        Create all decision variables for the optimization model.
        Only creates variables for slots where scheduling is actually allowed.

        NOTE:
        - Uses event_id instead of subject_id
        - Merged courses share the SAME event variables
        - Duplicate guards prevent re-creation
        """
        variables = {
            'lecture': {},
            'tutorial': {},
            'practical': {},
            'room_assignment': {},
            'room_penalty': {}, # cost variable, not decision variable
            'max_used_slot': model.NewIntVar(0, len(self.time_slots) - 1, "max_used_slot") # from 0 to 53, 9 per day, needed to finish timetable ASAP in the week
        }

        print("   📊 Creating decision variables (efficient slot-aware creation)...")

        # Counters for summary
        lecture_count = 0
        tutorial_count = 0
        practical_count = 0
        room_count = 0

        # ================================================================
        # CLASS VARIABLES (LECTURE / TUTORIAL / PRACTICAL)
        # ================================================================
        for subj in self.subjects:
            # pprint(subj, sort_dicts=False)
            # print("\n")
            event_id = self._get_event_id(subj)
            clean_id = event_id.replace("-", "_").replace(" ", "_").replace(".", "")
            # print(clean_id)

            # Allowed slots
            if subj.get("Is_GE_Lab", False):
                lecture_tutorial_slots = self._get_allowed_slots_for_subject(subj)
                practical_slots = self._get_allowed_slots_for_ge_practical(subj["Semester"])
                # print("Lecture Slots: ", lecture_tutorial_slots)
                # print("Practical Slots: ", practical_slots, "\n")
            else:
                allowed_slots = self._get_allowed_slots_for_subject(subj)
                lecture_tutorial_slots = allowed_slots
                practical_slots = allowed_slots
                # print("Lecture Slots: ", lecture_tutorial_slots)
                # print("Practical Slots: ", practical_slots, "\n")

            # ---------------- LECTURES ----------------
            if subj["Taught_Lecture_hours"] > 0:
                for t in lecture_tutorial_slots:
                    key = (event_id, t)
                    if key not in variables['lecture']: # Only one variable per unique event per slot
                        var_name = f"lec_{clean_id}_{t}"
                        variables['lecture'][key] = model.NewBoolVar(var_name) # Creating a new decision variable
                        # pprint(variables['lecture'], sort_dicts=False)
                        lecture_count += 1

            # ---------------- TUTORIALS ----------------
            if subj["Taught_Tutorial_hours"] > 0:
                for t in lecture_tutorial_slots:
                    key = (event_id, t)
                    if key not in variables['tutorial']:
                        var_name = f"tut_{clean_id}_{t}"
                        variables['tutorial'][key] = model.NewBoolVar(var_name)
                        tutorial_count += 1

            # ---------------- PRACTICALS ----------------
            if subj["Taught_Practical_hours"] > 0:
                for t in practical_slots:
                    key = (event_id, t)
                    if key not in variables['practical']:
                        var_name = f"prac_{clean_id}_{t}"
                        variables['practical'][key] = model.NewBoolVar(var_name)
                        practical_count += 1

        # ================================================================
        # ROOM ASSIGNMENT VARIABLES
        # ================================================================
        classrooms = Config.get_rooms_by_type("classroom")

        for subj in self.subjects:
            event_id = self._get_event_id(subj)
            clean_id = event_id.replace("-", "_").replace(" ", "_").replace(".", "")

            if subj.get("Is_GE_Lab", False):
                lecture_tutorial_slots = self._get_allowed_slots_for_subject(subj)
                practical_slots = self._get_allowed_slots_for_ge_practical(subj["Semester"])
            else:
                allowed_slots = self._get_allowed_slots_for_subject(subj)
                lecture_tutorial_slots = allowed_slots
                practical_slots = allowed_slots

            # -------- Lecture rooms --------
            if subj["Taught_Lecture_hours"] > 0:
                dept_labs = (
                    Config.get_labs_by_department(subj["Department"])
                    if subj["Department"] in Config.DEPARTMENT_LABS.values()
                    else []
                )

                for t in lecture_tutorial_slots:
                    for room in classrooms:
                        key = (event_id, t, room, 'lecture')
                        if key not in variables['room_assignment']:
                            room_clean = room.replace("-", "_")
                            var_name = f"room_{clean_id}_{t}_{room_clean}_lec"
                            variables['room_assignment'][key] = model.NewBoolVar(var_name)
                            room_count += 1

                    for lab in dept_labs:
                        key = (event_id, t, lab, 'lecture')
                        if key not in variables['room_assignment']:
                            lab_clean = lab.replace("-", "_")
                            var_name = f"room_{clean_id}_{t}_{lab_clean}_lec"
                            variables['room_assignment'][key] = model.NewBoolVar(var_name)
                            room_count += 1

            # -------- Tutorial rooms --------
            if subj["Taught_Tutorial_hours"] > 0:
                dept_labs = (
                    Config.get_labs_by_department(subj["Department"])
                    if subj["Department"] in Config.DEPARTMENT_LABS.values()
                    else []
                )

                for t in lecture_tutorial_slots:
                    for room in classrooms:
                        key = (event_id, t, room, 'tutorial')
                        if key not in variables['room_assignment']:
                            room_clean = room.replace("-", "_")
                            var_name = f"room_{clean_id}_{t}_{room_clean}_tut"
                            variables['room_assignment'][key] = model.NewBoolVar(var_name)
                            room_count += 1

                    for lab in dept_labs:
                        key = (event_id, t, lab, 'tutorial')
                        if key not in variables['room_assignment']:
                            lab_clean = lab.replace("-", "_")
                            var_name = f"room_{clean_id}_{t}_{lab_clean}_tut"
                            variables['room_assignment'][key] = model.NewBoolVar(var_name)
                            room_count += 1

            # -------- Practical rooms --------
            if subj["Taught_Practical_hours"] > 0:
                available_labs = Config.get_labs_by_department(subj["Department"])

                for t in practical_slots:
                    for lab in available_labs:
                        key = (event_id, t, lab, 'practical')
                        if key not in variables['room_assignment']:
                            lab_clean = lab.replace("-", "_")
                            var_name = f"room_{clean_id}_{t}_{lab_clean}_prac"
                            variables['room_assignment'][key] = model.NewBoolVar(var_name)
                            room_count += 1

        # ================================================================
        # ROOM PENALTY VARIABLES
        # ================================================================
        for subj in self.subjects:
            event_id = self._get_event_id(subj)
            clean_id = event_id.replace("-", "_").replace(" ", "_").replace(".", "")

            if subj.get("Is_GE_Lab", False):
                theory_slots = self._get_allowed_slots_for_subject(subj)
                practical_slots = self._get_allowed_slots_for_ge_practical(subj["Semester"])
            else:
                allowed_slots = self._get_allowed_slots_for_subject(subj)
                theory_slots = allowed_slots
                practical_slots = allowed_slots

            if subj["Lecture_hours"] > 0 or subj["Tutorial_hours"] > 0:
                for t in theory_slots:
                    key_over = (event_id, t, 'oversized')
                    key_under = (event_id, t, 'undersized')

                    if key_over not in variables['room_penalty']:
                        variables['room_penalty'][key_over] = model.NewIntVar(
                            0, 1000, f"penalty_over_{clean_id}_{t}"
                        )
                    if key_under not in variables['room_penalty']:
                        variables['room_penalty'][key_under] = model.NewIntVar(
                            0, 1000, f"penalty_under_{clean_id}_{t}"
                        )

            if subj["Practical_hours"] > 0:
                for t in practical_slots:
                    key_over = (event_id, t, 'oversized_lab')
                    key_under = (event_id, t, 'undersized_lab')

                    if key_over not in variables['room_penalty']:
                        variables['room_penalty'][key_over] = model.NewIntVar(
                            0, 1000, f"penalty_over_prac_{clean_id}_{t}"
                        )
                    if key_under not in variables['room_penalty']:
                        variables['room_penalty'][key_under] = model.NewIntVar(
                            0, 1000, f"penalty_under_prac_{clean_id}_{t}"
                        )
                        
        #Basic usage of the 3 for loops in this method:
        # lecture[(event, t)] → happens?
        # room_assignment[(event, t, room)] → where?
        # room_penalty[(event, t)] → how good?
        
        print(f"      • Lectures: {lecture_count}")
        print(f"      • Tutorials: {tutorial_count}")
        print(f"      • Practicals: {practical_count}")
        print(f"      • Room assignments: {room_count}")

        return variables

    def _add_hour_requirements(self, model: cp_model.CpModel, variables: Dict):
        """
        Ensure each scheduling EVENT meets exactly the required teaching hours.

        IMPORTANT DESIGN:
        - Merged courses are treated as ONE event → hours enforced once
        - Non-merged courses behave exactly as before
        - This constraint FORCES the solver to schedule classes
        """

        processed_merge_groups = set()

        for subj in self.subjects:
            merge_id = subj.get("Merge_Group_ID")

            # 🔹 For merged courses: enforce hours only ONCE
            if merge_id:
                if merge_id in processed_merge_groups:
                    continue
                processed_merge_groups.add(merge_id)

            event_id = self._get_event_id(subj)

            # ================================================================
            # LECTURES (mandatory)
            # ================================================================
            if subj["Lecture_hours"] > 0:
                lecture_vars = [
                    variables['lecture'][(event_id, t)]
                    for t in range(len(self.time_slots))
                    if (event_id, t) in variables['lecture']
                ]

                if lecture_vars:
                    model.Add(sum(lecture_vars) == subj["Taught_Lecture_hours"])

            # ================================================================
            # TUTORIALS (mandatory)
            # ================================================================
            if subj["Tutorial_hours"] > 0:
                tutorial_vars = [
                    variables['tutorial'][(event_id, t)]
                    for t in range(len(self.time_slots))
                    if (event_id, t) in variables['tutorial']
                ]

                if tutorial_vars:
                    model.Add(sum(tutorial_vars) == subj["Taught_Tutorial_hours"])

            # ================================================================
            # PRACTICALS (mandatory)
            # ================================================================
            if subj["Practical_hours"] > 0:
                practical_vars = [
                    variables['practical'][(event_id, t)]
                    for t in range(len(self.time_slots))
                    if (event_id, t) in variables['practical']
                ]

                if practical_vars:
                    model.Add(sum(practical_vars) == subj["Taught_Practical_hours"])
    
    def _add_room_assignment_constraints(self, model: cp_model.CpModel, variables: Dict):
        """
        Ensure each scheduled class is assigned to exactly one room.
        Also calculates room size mismatch penalties.
        """
        print("   ✅ Adding room assignment constraints")
        
        for subj in self.subjects:
            subject_id = self._build_subject_id(subj)
            student_count = subj["Students_count"]
            
            # ==================================================================
            # LECTURES - Must have exactly one room if scheduled
            # ==================================================================
            if subj["Lecture_hours"] > 0:
                for t in range(len(self.time_slots)):
                    lecture_var = variables['lecture'].get((subject_id, t))
                    
                    if lecture_var is not None:
                        # Get all possible room assignments
                        room_assignments = []
                        
                        for room in Config.get_rooms_by_type("classroom"):
                            if (subject_id, t, room, 'lecture') in variables['room_assignment']:
                                room_assignments.append(variables['room_assignment'][(subject_id, t, room, 'lecture')])
                        
                        # Labs as backup
                        for lab in [name for name, info in Config.ROOMS.items() if info["type"] == "lab"]:
                            if (subject_id, t, lab, 'lecture') in variables['room_assignment']:
                                room_assignments.append(variables['room_assignment'][(subject_id, t, lab, 'lecture')])
                        
                        if room_assignments:
                            # Exactly 1 room if lecture is scheduled
                            model.Add(sum(room_assignments) == 1).OnlyEnforceIf(lecture_var)
                            model.Add(sum(room_assignments) == 0).OnlyEnforceIf(lecture_var.Not())
                            
                            # Add room fit penalties
                            self._add_room_fit_penalties(model, variables, subject_id, t, 
                                                        student_count, 'lecture')
                            
                            # ✅ NEW: Add penalty for using labs instead of classrooms
                            self._add_theory_in_lab_penalty(model, variables, subject_id, t, 
                                                            subj["Department"], 'lecture')
            
            # ==================================================================
            # TUTORIALS - Must have exactly one room if scheduled
            # ==================================================================
            if subj["Tutorial_hours"] > 0:
                for t in range(len(self.time_slots)):
                    tutorial_var = variables['tutorial'].get((subject_id, t))
                    
                    if tutorial_var is not None:
                        room_assignments = []
                        
                        for room in Config.get_rooms_by_type("classroom"):
                            if (subject_id, t, room, 'tutorial') in variables['room_assignment']:
                                room_assignments.append(variables['room_assignment'][(subject_id, t, room, 'tutorial')])
                        
                        # Labs as backup
                        for lab in [name for name, info in Config.ROOMS.items() if info["type"] == "lab"]:
                            if (subject_id, t, lab, 'tutorial') in variables['room_assignment']:
                                room_assignments.append(variables['room_assignment'][(subject_id, t, lab, 'tutorial')])
                        
                        if room_assignments:
                            model.Add(sum(room_assignments) == 1).OnlyEnforceIf(tutorial_var)
                            model.Add(sum(room_assignments) == 0).OnlyEnforceIf(tutorial_var.Not())
                            
                            # Add room fit penalties
                            self._add_room_fit_penalties(model, variables, subject_id, t,
                                                        student_count, 'tutorial')
                            
                            # ✅ NEW: Add penalty for using labs instead of classrooms
                            self._add_theory_in_lab_penalty(model, variables, subject_id, t,
                                                            subj["Department"], 'tutorial')
            
            # ==================================================================
            # PRACTICALS - Must have exactly one lab if scheduled
            # ==================================================================
            if subj["Practical_hours"] > 0:
                available_labs = Config.get_labs_by_department(subj["Department"])
                
                for t in range(len(self.time_slots)):
                    practical_var = variables['practical'].get((subject_id, t))
                    
                    if practical_var is not None:
                        room_assignments = [
                            variables['room_assignment'][(subject_id, t, lab, 'practical')]
                            for lab in available_labs
                            if (subject_id, t, lab, 'practical') in variables['room_assignment']
                        ]
                        
                        if room_assignments:
                            # Exactly 1 lab if practical is scheduled
                            model.Add(sum(room_assignments) == 1).OnlyEnforceIf(practical_var)
                            model.Add(sum(room_assignments) == 0).OnlyEnforceIf(practical_var.Not())
                            
                            # Add lab fit penalties
                            self._add_lab_fit_penalties(model, variables, subject_id, t,
                                                        student_count, available_labs)
    
    def _add_room_fit_penalties(self, model: cp_model.CpModel, variables: Dict,
                                subject_id: str, time: int, student_count: int,
                                class_type: str):
        """
        Calculate penalties for room size mismatch (theory classes in classrooms).
        
        Args:
            model: CP-SAT model
            variables: Variables dictionary
            subject_id: Subject identifier
            time: Time slot index
            student_count: Number of students
            class_type: 'lecture' or 'tutorial'
        """
        
        # For merged courses, use combined student count
        # Find if this subject is part of a merge group
        for subj in self.subjects:
            if self._build_subject_id(subj) == subject_id:
                merge_group_id = subj.get("Merge_Group_ID")
                if merge_group_id:
                    # Sum students from all merged courses
                    combined_count = sum(
                        s["Students_count"] 
                        for s in self.subjects 
                        if s.get("Merge_Group_ID") == merge_group_id
                    )
                    student_count = combined_count
                break
        
        classrooms = Config.get_rooms_by_type("classroom")
        
        for room in classrooms:
            if (subject_id, time, room, class_type) not in variables['room_assignment']:
                continue
            
            room_var = variables['room_assignment'][(subject_id, time, room, class_type)]
            room_info = Config.ROOMS[room]
            
            capacity_min = room_info["capacity_min"]
            capacity_max = room_info["capacity_max"]
            
            # Perfect fit: students within capacity range
            if capacity_min <= student_count <= capacity_max:
                # No penalty
                pass
            
            # Oversized: room bigger than needed
            elif student_count < capacity_min:
                waste = capacity_min - student_count
                penalty = waste * Config.PENALTY_WEIGHTS["oversized_room"]
                
                # If this room is assigned, add oversized penalty
                model.Add(
                    variables['room_penalty'][(subject_id, time, 'oversized')] >= penalty
                ).OnlyEnforceIf(room_var)
            
            # Undersized: room smaller than needed
            elif student_count > capacity_max:
                overflow = student_count - capacity_max
                penalty = overflow * Config.PENALTY_WEIGHTS["undersized_room"]
                
                # If this room is assigned, add undersized penalty
                model.Add(
                    variables['room_penalty'][(subject_id, time, 'undersized')] >= penalty
                ).OnlyEnforceIf(room_var)
    
    def _add_lab_fit_penalties(self, model: cp_model.CpModel, variables: Dict,
                               subject_id: str, time: int, student_count: int,
                               available_labs: List[str]):
        """
        Calculate penalties for lab size mismatch (practical classes).
        Labs now have ±3 capacity tolerance.
        
        Args:
            model: CP-SAT model
            variables: Variables dictionary
            subject_id: Subject identifier
            time: Time slot index
            student_count: Number of students
            available_labs: List of available labs for this subject
        """
        for lab in available_labs:
            if (subject_id, time, lab, 'practical') not in variables['room_assignment']:
                continue
            
            lab_var = variables['room_assignment'][(subject_id, time, lab, 'practical')]
            lab_info = Config.ROOMS[lab]
            
            # Lab capacity with ±3 tolerance
            capacity_center = lab_info["capacity_max"]
            capacity_min = capacity_center - 3
            capacity_max = capacity_center + 3
            
            # Perfect fit: students within tolerance range
            if capacity_min <= student_count <= capacity_max:
                # No penalty
                pass
            
            # Oversized: lab bigger than needed
            elif student_count < capacity_min:
                waste = capacity_min - student_count
                penalty = waste * Config.PENALTY_WEIGHTS["oversized_room"]
                
                model.Add(
                    variables['room_penalty'][(subject_id, time, 'oversized_lab')] >= penalty
                ).OnlyEnforceIf(lab_var)
            
            # Undersized: lab smaller than needed
            elif student_count > capacity_max:
                overflow = student_count - capacity_max
                penalty = overflow * Config.PENALTY_WEIGHTS["undersized_room"]
                
                model.Add(
                    variables['room_penalty'][(subject_id, time, 'undersized_lab')] >= penalty
                ).OnlyEnforceIf(lab_var)
    
    def _add_theory_in_lab_penalty(self, model: cp_model.CpModel, variables: Dict,
                               subject_id: str, time: int, department: str,
                               class_type: str):
        """
        Add heavy penalty for using labs for theory classes (lectures/tutorials).
        Labs should only be used as last resort when all classrooms are full.
        
        Args:
            model: CP-SAT model
            variables: Variables dictionary
            subject_id: Subject identifier
            time: Time slot index
            department: Department name
            class_type: 'lecture' or 'tutorial'
        """
        # Get department-specific labs
        dept_labs = Config.get_labs_by_department(department) if department in Config.DEPARTMENT_LABS.values() else []
        
        # Create penalty variable if it doesn't exist
        if (subject_id, time, 'theory_in_lab') not in variables['room_penalty']:
            clean_id = subject_id.replace("-", "_").replace(" ", "_").replace(".", "")
            var_name = f"penalty_lab_{clean_id}_{time}"
            variables['room_penalty'][(subject_id, time, 'theory_in_lab')] = model.NewIntVar(0, 1000, var_name)
        
        penalty_var = variables['room_penalty'][(subject_id, time, 'theory_in_lab')]
        
        # Check if any lab is being used
        lab_usage_vars = []
        for lab in dept_labs:
            lab_var = variables['room_assignment'].get((subject_id, time, lab, class_type))
            if lab_var is not None:
                lab_usage_vars.append(lab_var)
        
        if lab_usage_vars:
            # If ANY lab is used, apply heavy penalty
            any_lab_used = model.NewBoolVar(f"any_lab_{subject_id}_{time}_{class_type}".replace("-", "_").replace(" ", "_").replace(".", ""))
            model.AddBoolOr(lab_usage_vars).OnlyEnforceIf(any_lab_used)
            model.AddBoolAnd([lv.Not() for lv in lab_usage_vars]).OnlyEnforceIf(any_lab_used.Not())
            
            # Apply penalty if lab is used
            model.Add(penalty_var == Config.PENALTY_WEIGHTS["theory_in_lab"]).OnlyEnforceIf(any_lab_used)
            model.Add(penalty_var == 0).OnlyEnforceIf(any_lab_used.Not())
    
    def _add_theory_can_use_labs(self, model: cp_model.CpModel, variables: Dict):
        """
        Allow theory classes (lectures/tutorials) to use labs as backup when classrooms are full.
        This provides flexibility in room assignment.
        """
        print("   ✅ Adding theory-can-use-labs flexibility")
        
        # Note: Room assignment variables for labs are already created in _create_variables()
        # This method is kept for clarity/documentation, but the actual flexibility
        # is enabled by creating lab room assignment variables for lectures/tutorials
        pass
    
    def _add_teacher_clash(self, model: cp_model.CpModel, variables: Dict):
        """
        Prevent teacher from teaching multiple classes simultaneously.
        Handles main teachers, co-teachers, and assistant teachers.
        """
        for t in range(len(self.time_slots)):
            # Build teacher-to-classes mapping for this time slot
            teacher_classes = {}
            
            for subj in self.subjects:
                subject_id = self._build_subject_id(subj)
                
                # Main teacher classes
                main_teacher = subj["Teacher"]
                if main_teacher not in teacher_classes:
                    teacher_classes[main_teacher] = []
                
                # Lectures
                if (subject_id, t) in variables['lecture']:
                    teacher_classes[main_teacher].append(variables['lecture'][(subject_id, t)])
                
                # Tutorials
                if (subject_id, t) in variables['tutorial']:
                    teacher_classes[main_teacher].append(variables['tutorial'][(subject_id, t)])
                
                # Practicals - main teacher present for all hours
                if (subject_id, t) in variables['practical']:
                    teacher_classes[main_teacher].append(variables['practical'][(subject_id, t)])
                
                # Co-teachers (teach alongside main teacher)
                for co_teacher in subj.get("Co_Teachers", []):
                    if co_teacher not in teacher_classes:
                        teacher_classes[co_teacher] = []
                    
                    # Co-teacher present for all classes
                    if (subject_id, t) in variables['lecture']:
                        teacher_classes[co_teacher].append(variables['lecture'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['tutorial']:
                        teacher_classes[co_teacher].append(variables['tutorial'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['practical']:
                        teacher_classes[co_teacher].append(variables['practical'][(subject_id, t)])
            
            # Apply clash constraints
            for teacher, classes_at_t in teacher_classes.items():
                if classes_at_t:
                    model.Add(sum(classes_at_t) <= 1)
    
    def _add_room_clash(self, model: cp_model.CpModel, variables: Dict):
        """
        Each specific room can only host one class at a time.
        For practicals with 2-hour blocks, accounts for block occupancy.
        """
        print("   ✅ Adding room clash prevention")
        
        for t in range(len(self.time_slots)):
            # ==============================================================
            # CLASSROOMS - At most 1 lecture/tutorial per room per time
            # ==============================================================
            for room in Config.get_rooms_by_type("classroom"):
                classes_in_room = []
                
                for subj in self.subjects:
                    subject_id = self._build_subject_id(subj)
                    
                    # Lectures at time t
                    if (subject_id, t, room, 'lecture') in variables['room_assignment']:
                        classes_in_room.append(variables['room_assignment'][(subject_id, t, room, 'lecture')])
                    
                    # Tutorials at time t
                    if (subject_id, t, room, 'tutorial') in variables['room_assignment']:
                        classes_in_room.append(variables['room_assignment'][(subject_id, t, room, 'tutorial')])
                
                if classes_in_room:
                    model.Add(sum(classes_in_room) <= 1)
            
            # ==============================================================
            # LABS - At most 1 practical per lab per time (accounting for 2-hour blocks)
            # ==============================================================
            for lab in [name for name, info in Config.ROOMS.items() if info["type"] == "lab"]:
                classes_in_lab = []
                
                for subj in self.subjects:
                    subject_id = self._build_subject_id(subj)
                    
                    # Case 1: Practical STARTS at time t
                    if (subject_id, t, lab, 'practical') in variables['room_assignment']:
                        classes_in_lab.append(variables['room_assignment'][(subject_id, t, lab, 'practical')])
                    
                    # Case 2: 2-hour practical started at t-1 and occupies t
                    # Only if practical_consecutive constraint is enabled and forms actual 2-hour block
                    if (self.constraint_selector.is_enabled("practical_consecutive") and 
                        self._is_consecutive_slot(t) and t > 0):
                        
                        if (subject_id, t - 1) in variables.get('practical_is_2hour_block', {}):
                            block_var = variables['practical_is_2hour_block'][(subject_id, t - 1)]
                            room_var = variables['room_assignment'].get((subject_id, t - 1, lab, 'practical'))
                            
                            if room_var is not None:
                                # Helper: This lab is occupied at t by block from t-1
                                clean_id = subject_id.replace("-", "_").replace(" ", "_").replace(".", "")
                                lab_clean = lab.replace("-", "_")
                                occupies_var = model.NewBoolVar(f"occupies_{clean_id}_{lab_clean}_{t}")
                                
                                # occupies = (block[t-1] = 1 AND room[t-1] = this_lab)
                                model.AddBoolAnd([block_var, room_var]).OnlyEnforceIf(occupies_var)
                                model.AddBoolOr([block_var.Not(), room_var.Not()]).OnlyEnforceIf(occupies_var.Not())
                                
                                classes_in_lab.append(occupies_var)
                
                if classes_in_lab:
                    model.Add(sum(classes_in_lab) <= 1)
    
    def _add_course_semester_clash(self, model: cp_model.CpModel, variables: Dict):
        """
        Course-semester cannot have multiple classes at same time.
        Students in a course-semester can only attend one class at a time.
        
        NOTE: For split teaching, ALL teachers' classes are checked for clashes
        (they teach same students at different times).
        For merged courses, only one entry is checked (they teach at same time).
        """
        for t in range(len(self.time_slots)):
            for course_sem in self.course_semesters:
                classes_at_t = []
                processed_merge_groups = set()
                
                for subj in self.subjects:
                    if subj["Course_Semester"] != course_sem:
                        continue
                    
                    subject_id = self._build_subject_id(subj)
                    
                    # ✅ Only skip duplicate entries for MERGED courses
                    # (Split teaching entries should ALL be included)
                    merge_group_id = subj.get("Merge_Group_ID")
                    
                    if merge_group_id and merge_group_id in processed_merge_groups:
                        continue
                    
                    if merge_group_id:
                        processed_merge_groups.add(merge_group_id)
                    
                    # Add all class types at this time
                    if (subject_id, t) in variables['lecture']:
                        classes_at_t.append(variables['lecture'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['tutorial']:
                        classes_at_t.append(variables['tutorial'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['practical']:
                        classes_at_t.append(variables['practical'][(subject_id, t)])
                
                if classes_at_t:
                    # At most 1 class at time t for this course-semester
                    model.Add(sum(classes_at_t) <= 1)
    
    def _add_teacher_load(self, model: cp_model.CpModel, variables: Dict):
        """
        Limit total hours per teacher per week to maximum allowed.
        """
        for teacher in self.teachers:
            total_hours = []
            
            for subj in self.subjects:
                if subj["Teacher"] == teacher:
                    subject_id = self._build_subject_id(subj)
                    
                    for t in range(len(self.time_slots)):
                        if (subject_id, t) in variables['lecture']:
                            total_hours.append(variables['lecture'][(subject_id, t)])
                        
                        if (subject_id, t) in variables['tutorial']:
                            total_hours.append(variables['tutorial'][(subject_id, t)])
                        
                        if (subject_id, t) in variables['practical']:
                            total_hours.append(variables['practical'][(subject_id, t)])
            
            if total_hours:
                model.Add(sum(total_hours) <= Config.MAX_HOURS_PER_TEACHER)
    
    def _add_same_subject_no_concurrency(self, model: cp_model.CpModel, variables: Dict):
        """
        Different sections of the SAME subject cannot run concurrently.
        ONLY applies to DSC/DSE subjects (students take same subjects).
        SKIPS merged courses (they're intentionally shared across courses).
        """
        print("      → Adding no-concurrency constraint for same subject sections")
        
        # Group subjects by (COURSE, semester, subject_name, subject_type)
        subject_groups = {}
        for subj in self.subjects:
            # SKIP merged courses entirely
            if subj.get("Is_Merged", False):
                continue
            
            # ONLY apply to DSC/DSE subjects
            if subj["Subject_type"] in ["DSC", "DSE"]:
                key = (subj["Course"], subj["Semester"], subj["Subject"], subj["Subject_type"])
                if key not in subject_groups:
                    subject_groups[key] = []
                subject_groups[key].append(subj)
        
        # For DSC/DSE groups with multiple sections, add no-concurrency
        for key, subjects_in_group in subject_groups.items():
            # Only add constraint if there are multiple sections
            if len(subjects_in_group) <= 1:
                continue
            
            course, semester, subject_name, subject_type = key
            print(f"         → {subject_type} '{subject_name}' [{course}] Sem{semester}: {len(subjects_in_group)} sections - no concurrency")
            
            # For each time slot, at most ONE section can be scheduled
            for t in range(len(self.time_slots)):
                classes_at_t = []
                
                for subj in subjects_in_group:
                    subject_id = self._build_subject_id(subj)
                    
                    if (subject_id, t) in variables['lecture']:
                        classes_at_t.append(variables['lecture'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['tutorial']:
                        classes_at_t.append(variables['tutorial'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['practical']:
                        classes_at_t.append(variables['practical'][(subject_id, t)])
                
                # Only add constraint if there are classes to constrain
                if len(classes_at_t) > 0:
                    model.Add(sum(classes_at_t) <= 1)
    
    def _add_merged_course_synchronization(self, model: cp_model.CpModel, variables: Dict):
        """
        Force merged courses to be scheduled at the same TIME (but can use different rooms).
        Merged courses share a single teacher and must run simultaneously.
        
        NOTE: For practicals, we allow different labs to accommodate large student counts.
        """
        print("   ✅ Adding merged course synchronization")
        
        # Group subjects by merge_group_id
        merge_groups = {}
        for subj in self.subjects:
            merge_id = subj.get("Merge_Group_ID")
            if merge_id:
                if merge_id not in merge_groups:
                    merge_groups[merge_id] = []
                merge_groups[merge_id].append(subj)
        
        # For each merge group, enforce synchronization
        for merge_id, subjects_in_group in merge_groups.items():
            if len(subjects_in_group) < 2:
                continue
            
            # Calculate combined student count
            combined_students = sum(s["Students_count"] for s in subjects_in_group)
            max_lab_capacity = max(
                Config.ROOMS[lab]["capacity_max"] 
                for lab in Config.get_labs_by_department(subjects_in_group[0]["Department"])
            ) if subjects_in_group[0]["Practical_hours"] > 0 else 0
            
            # Check if students fit in single lab
            needs_multiple_labs = (subjects_in_group[0]["Practical_hours"] > 0 and 
                                combined_students > max_lab_capacity)
            
            if needs_multiple_labs:
                print(f"      → Syncing {len(subjects_in_group)} courses: {', '.join([s['Course'] for s in subjects_in_group])} "
                    f"({combined_students} students - MULTIPLE LABS)")
            else:
                print(f"      → Syncing {len(subjects_in_group)} courses: {', '.join([s['Course'] for s in subjects_in_group])}")
            
            # Use first subject as reference
            ref_subj = subjects_in_group[0]
            ref_id = self._build_subject_id(ref_subj)
            
            # All other subjects must match
            for other_subj in subjects_in_group[1:]:
                other_id = self._build_subject_id(other_subj)
                
                # ================================================================
                # LECTURES - Must be at same times AND same room
                # ================================================================
                for t in range(len(self.time_slots)):
                    if (ref_id, t) in variables['lecture'] and (other_id, t) in variables['lecture']:
                        # Same time
                        model.Add(
                            variables['lecture'][(ref_id, t)] == variables['lecture'][(other_id, t)]
                        )
                        
                        # Same room (lectures can share - single teacher)
                        for room in Config.get_rooms_by_type("classroom"):
                            ref_room = variables['room_assignment'].get((ref_id, t, room, 'lecture'))
                            other_room = variables['room_assignment'].get((other_id, t, room, 'lecture'))
                            
                            if ref_room is not None and other_room is not None:
                                model.Add(ref_room == other_room)
                        
                        # Also check labs as backup
                        for lab in [name for name, info in Config.ROOMS.items() if info["type"] == "lab"]:
                            ref_room = variables['room_assignment'].get((ref_id, t, lab, 'lecture'))
                            other_room = variables['room_assignment'].get((other_id, t, lab, 'lecture'))
                            
                            if ref_room is not None and other_room is not None:
                                model.Add(ref_room == other_room)
                
                # ================================================================
                # TUTORIALS - Must be at same times AND same room
                # ================================================================
                for t in range(len(self.time_slots)):
                    if (ref_id, t) in variables['tutorial'] and (other_id, t) in variables['tutorial']:
                        # Same time
                        model.Add(
                            variables['tutorial'][(ref_id, t)] == variables['tutorial'][(other_id, t)]
                        )
                        
                        # Same room
                        for room in Config.get_rooms_by_type("classroom"):
                            ref_room = variables['room_assignment'].get((ref_id, t, room, 'tutorial'))
                            other_room = variables['room_assignment'].get((other_id, t, room, 'tutorial'))
                            
                            if ref_room is not None and other_room is not None:
                                model.Add(ref_room == other_room)
                        
                        for lab in [name for name, info in Config.ROOMS.items() if info["type"] == "lab"]:
                            ref_room = variables['room_assignment'].get((ref_id, t, lab, 'tutorial'))
                            other_room = variables['room_assignment'].get((other_id, t, lab, 'tutorial'))
                            
                            if ref_room is not None and other_room is not None:
                                model.Add(ref_room == other_room)
                
                # ================================================================
                # PRACTICALS - Must be at same times, but CAN use different labs
                # (to accommodate large student counts that exceed single lab capacity)
                # ================================================================
                for t in range(len(self.time_slots)):
                    if (ref_id, t) in variables['practical'] and (other_id, t) in variables['practical']:
                        # ✅ FIX: Only enforce same TIME, not same ROOM
                        model.Add(
                            variables['practical'][(ref_id, t)] == variables['practical'][(other_id, t)]
                        )
                        
                        # ❌ REMOVED: Room synchronization for practicals
                        # They can use different labs if needed for capacity
    
    def _add_split_teaching_no_concurrency(self, model: cp_model.CpModel, variables: Dict):
        """
        Teachers in the same split teaching group cannot teach at the same time.
        They're teaching different portions of the same subject to the same students.
        """
        print("   ✅ Adding split teaching no-concurrency constraint")
        
        # Group subjects by Split_Group_ID
        split_groups = {}
        for subj in self.subjects:
            split_id = subj.get("Split_Group_ID")
            if split_id:
                if split_id not in split_groups:
                    split_groups[split_id] = []
                split_groups[split_id].append(subj)
        
        # For each split group, prevent concurrent scheduling
        for split_id, subjects_in_group in split_groups.items():
            if len(subjects_in_group) < 2:
                continue
            
            print(f"      → Split group: {subjects_in_group[0]['Subject']} - {len(subjects_in_group)} teachers")
            
            # For each time slot, at most ONE teacher from this group can teach
            for t in range(len(self.time_slots)):
                classes_at_t = []
                
                for subj in subjects_in_group:
                    subject_id = self._build_subject_id(subj)
                    
                    if (subject_id, t) in variables['lecture']:
                        classes_at_t.append(variables['lecture'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['tutorial']:
                        classes_at_t.append(variables['tutorial'][(subject_id, t)])
                    
                    if (subject_id, t) in variables['practical']:
                        classes_at_t.append(variables['practical'][(subject_id, t)])
                
                if classes_at_t:
                    model.Add(sum(classes_at_t) <= 1)
    
    def _add_practical_consecutive(self, model: cp_model.CpModel, variables: Dict):
        """
        Soft constraint: Prefer 2-hour consecutive practical blocks.
        Creates explicit helper variables to track actual 2-hour blocks.
        Allows 1-hour isolated blocks as fallback with penalty.
        
        Penalty: 50 points per isolated practical hour (Option A - stronger incentive).
        
        This constraint also enforces that 2-hour blocks must use the same room.
        """
        print("   ✅ Adding practical consecutive preference (soft constraint with 2-hour block tracking)")
        
        # Create helper variables for 2-hour blocks
        variables['practical_is_2hour_block'] = {}
        variables['practical_non_consecutive_penalty'] = {}
        
        for subj in self.subjects:
            if subj["Practical_hours"] == 0:
                continue
            
            subject_id = self._build_subject_id(subj)
            clean_id = subject_id.replace("-", "_").replace(" ", "_").replace(".", "")
            
            # ================================================================
            # Step 1: Create 2-hour block tracker variables
            # ================================================================
            for t in range(len(self.time_slots) - 1):
                # Check if t and t+1 are consecutive (same day)
                if not self._is_consecutive_slot(t + 1):
                    continue
                
                # Skip if either slot doesn't have practical variables
                if (subject_id, t) not in variables['practical']:
                    continue
                if (subject_id, t + 1) not in variables['practical']:
                    continue
                
                # Create: Is this a 2-hour block starting at t?
                var_name = f"prac_2hr_{clean_id}_{t}"
                block_var = model.NewBoolVar(var_name)
                variables['practical_is_2hour_block'][(subject_id, t)] = block_var
                
                # Link: block_var = 1 IFF (practical[t] = 1 AND practical[t+1] = 1)
                practical_t = variables['practical'][(subject_id, t)]
                practical_t1 = variables['practical'][(subject_id, t + 1)]
                
                # block_var = 1 => both practicals must be scheduled
                model.AddImplication(block_var, practical_t)
                model.AddImplication(block_var, practical_t1)
                
                # both practicals = 1 => block_var = 1
                both_scheduled = model.NewBoolVar(f"both_{clean_id}_{t}")
                model.AddBoolAnd([practical_t, practical_t1]).OnlyEnforceIf(both_scheduled)
                model.Add(practical_t + practical_t1 < 2).OnlyEnforceIf(both_scheduled.Not())
                model.AddImplication(both_scheduled, block_var)
                
                # ================================================================
                # Step 2: If forming 2-hour block, MUST use same room
                # ================================================================
                available_labs = Config.get_labs_by_department(subj["Department"])
                
                for lab in available_labs:
                    room_t = variables['room_assignment'].get((subject_id, t, lab, 'practical'))
                    room_t1 = variables['room_assignment'].get((subject_id, t + 1, lab, 'practical'))
                    
                    if room_t is not None and room_t1 is not None:
                        # If 2-hour block is active, both hours must use same room
                        # room_t = room_t1 when block_var = 1
                        model.Add(room_t == room_t1).OnlyEnforceIf(block_var)
            
            # ================================================================
            # Step 3: Add penalties for isolated (non-2-hour) practicals
            # Penalty per isolated hour (Option A)
            # ================================================================
            for t in range(len(self.time_slots)):
                if (subject_id, t) not in variables['practical']:
                    continue
                
                practical_t = variables['practical'][(subject_id, t)]
                
                # Check if this practical is part of any 2-hour block
                is_part_of_block = model.NewBoolVar(f"in_block_{clean_id}_{t}")
                
                block_conditions = []
                
                # Case 1: Starts a 2-hour block at t
                if (subject_id, t) in variables['practical_is_2hour_block']:
                    block_conditions.append(variables['practical_is_2hour_block'][(subject_id, t)])
                
                # Case 2: Is the second hour of a block that started at t-1
                if t > 0 and self._is_consecutive_slot(t):
                    if (subject_id, t - 1) in variables['practical_is_2hour_block']:
                        block_conditions.append(variables['practical_is_2hour_block'][(subject_id, t - 1)])
                
                if block_conditions:
                    # is_part_of_block = 1 if ANY block condition is true
                    model.AddBoolOr(block_conditions).OnlyEnforceIf(is_part_of_block)
                    model.AddBoolAnd([bc.Not() for bc in block_conditions]).OnlyEnforceIf(is_part_of_block.Not())
                else:
                    # No possible blocks => always isolated
                    model.Add(is_part_of_block == 0)
                
                # Create penalty variable
                penalty_var = model.NewIntVar(0, 50, f"penalty_isolated_{clean_id}_{t}")
                variables['practical_non_consecutive_penalty'][(subject_id, t)] = penalty_var
                
                # Penalty = 50 if (practical scheduled AND not part of 2-hour block)
                is_isolated = model.NewBoolVar(f"isolated_{clean_id}_{t}")
                model.AddBoolAnd([practical_t, is_part_of_block.Not()]).OnlyEnforceIf(is_isolated)
                model.AddBoolOr([practical_t.Not(), is_part_of_block]).OnlyEnforceIf(is_isolated.Not())
                
                model.Add(penalty_var == Config.PENALTY_WEIGHTS["isolated_practical"]).OnlyEnforceIf(is_isolated)
                model.Add(penalty_var == 0).OnlyEnforceIf(is_isolated.Not())
    
    def _add_max_consecutive_classes(self, model: cp_model.CpModel, variables: Dict):
        """
        Limit maximum consecutive classes for students and teachers.
        Prevents too many back-to-back classes which causes fatigue.
        """
        max_consecutive = self.constraint_selector.get_max_consecutive_hours()
        
        # For each course-semester (students)
        for course_sem in self.course_semesters:
            for day_idx in range(len(Config.DAYS)):
                for start_slot in range(len(self.slots) - max_consecutive):
                    consecutive_classes = []
                    
                    for offset in range(max_consecutive + 1):
                        t = day_idx * len(self.slots) + start_slot + offset
                        
                        for subj in self.subjects:
                            if subj["Course_Semester"] == course_sem:
                                subject_id = self._build_subject_id(subj)
                                
                                if (subject_id, t) in variables['lecture']:
                                    consecutive_classes.append(variables['lecture'][(subject_id, t)])
                                if (subject_id, t) in variables['tutorial']:
                                    consecutive_classes.append(variables['tutorial'][(subject_id, t)])
                                if (subject_id, t) in variables['practical']:
                                    consecutive_classes.append(variables['practical'][(subject_id, t)])
                    
                    if consecutive_classes:
                        model.Add(sum(consecutive_classes) <= max_consecutive)
        
        # For each teacher
        for teacher in self.teachers:
            for day_idx in range(len(Config.DAYS)):
                for start_slot in range(len(self.slots) - max_consecutive):
                    consecutive_classes = []
                    
                    for offset in range(max_consecutive + 1):
                        t = day_idx * len(self.slots) + start_slot + offset
                        
                        for subj in self.subjects:
                            if subj["Teacher"] == teacher:
                                subject_id = self._build_subject_id(subj)
                                
                                if (subject_id, t) in variables['lecture']:
                                    consecutive_classes.append(variables['lecture'][(subject_id, t)])
                                if (subject_id, t) in variables['tutorial']:
                                    consecutive_classes.append(variables['tutorial'][(subject_id, t)])
                                if (subject_id, t) in variables['practical']:
                                    consecutive_classes.append(variables['practical'][(subject_id, t)])
                    
                    if consecutive_classes:
                        model.Add(sum(consecutive_classes) <= max_consecutive)
    
    def _add_max_daily_hours_students(self, model: cp_model.CpModel, variables: Dict):
        """
        Limit maximum hours per day for students.
        Prevents overloading students with too many classes in one day.
        """
        max_hours = self.constraint_selector.get_max_daily_hours_students()
        
        for course_sem in self.course_semesters:
            for day_idx in range(len(Config.DAYS)):
                daily_hours = []
                
                for slot_idx in range(len(self.slots)):
                    t = day_idx * len(self.slots) + slot_idx
                    
                    for subj in self.subjects:
                        if subj["Course_Semester"] == course_sem:
                            subject_id = self._build_subject_id(subj)
                            
                            if (subject_id, t) in variables['lecture']:
                                daily_hours.append(variables['lecture'][(subject_id, t)])
                            if (subject_id, t) in variables['tutorial']:
                                daily_hours.append(variables['tutorial'][(subject_id, t)])
                            if (subject_id, t) in variables['practical']:
                                daily_hours.append(variables['practical'][(subject_id, t)])
                
                if daily_hours:
                    model.Add(sum(daily_hours) <= max_hours)
    
    def _add_max_daily_hours_teachers(self, model: cp_model.CpModel, variables: Dict):
        """
        Limit maximum teaching hours per day for teachers.
        Prevents teacher fatigue from too many classes in one day.
        """
        max_hours = self.constraint_selector.get_max_daily_hours_teachers()
        
        for teacher in self.teachers:
            for day_idx in range(len(Config.DAYS)):
                daily_hours = []
                
                for slot_idx in range(len(self.slots)):
                    t = day_idx * len(self.slots) + slot_idx
                    
                    for subj in self.subjects:
                        if subj["Teacher"] == teacher:
                            subject_id = self._build_subject_id(subj)
                            
                            if (subject_id, t) in variables['lecture']:
                                daily_hours.append(variables['lecture'][(subject_id, t)])
                            if (subject_id, t) in variables['tutorial']:
                                daily_hours.append(variables['tutorial'][(subject_id, t)])
                            if (subject_id, t) in variables['practical']:
                                daily_hours.append(variables['practical'][(subject_id, t)])
                
                if daily_hours:
                    model.Add(sum(daily_hours) <= max_hours)
    
    def _add_objective_function(self, model: cp_model.CpModel, variables: Dict):
        """
        Add objective function to minimize penalties and optimize schedule quality.
        
        Always minimizes:
        - Room size mismatch penalties (oversized/undersized)
        - GE practical using regular GE lecture slots (30 per hour)
        
        Additionally minimizes (if early_completion enabled):
        - Practical isolation penalties (if practical_consecutive enabled)
        - Day usage (prefer earlier days in week)
        - Latest slot used (prefer ending classes early)
        """
        print("   ✅ Adding objective function")
        
        # ================================================================
        # 1. Room Penalties (ALWAYS ON)
        # ================================================================
        total_room_penalty = sum(
            variables['room_penalty'].get((subject_id, t, penalty_type), 0)
            for subject_id, t, penalty_type in variables['room_penalty'].keys()
        )
        
        # ================================================================
        # 2. GE Practical using Regular GE Lecture Slots Penalty (ALWAYS ON)
        # ================================================================
        ge_lecture_penalty = 0
        for subj in self.subjects:
            if subj.get("Is_GE_Lab", False):
                subject_id = self._build_subject_id(subj)
                ge_lecture_slots = set(Config.get_fixed_slot_indices("GE"))
                
                for t in ge_lecture_slots:
                    if (subject_id, t) in variables['practical']:
                        # Penalize using lecture slots: 30 points per hour
                        ge_lecture_penalty += variables['practical'][(subject_id, t)] * Config.PENALTY_WEIGHTS["ge_lecture_slot_usage"]
        
        # ================================================================
        # 3. Practical Consecutive Penalties (if enabled)
        # ================================================================
        total_practical_penalty = 0
        if self.constraint_selector.is_enabled("practical_consecutive"):
            if 'practical_non_consecutive_penalty' in variables:
                total_practical_penalty = sum(
                    variables['practical_non_consecutive_penalty'].get((subject_id, t), 0)
                    for subject_id, t in variables['practical_non_consecutive_penalty'].keys()
                )
        
        # ================================================================
        # 4. Early Completion Objective (if enabled)
        # ================================================================
        if self.constraint_selector.is_enabled("early_completion"):
            print("   ✅ Adding early completion objective (minimize day usage + latest slot)")
            
            # Track which days are used
            day_used = {}
            for day_idx in range(len(Config.DAYS)):
                day_used[day_idx] = model.NewBoolVar(f"day_{day_idx}_used")
            
            # Get fixed slot indices (exclude from early completion tracking)
            fixed_indices = set()
            for semester in [1, 3, 5, 7]:  # Odd semesters
                fixed_types = Config.get_fixed_slot_types_for_semester(semester)
                for fixed_type in fixed_types:
                    fixed_indices.update(Config.get_fixed_slot_indices(fixed_type, semester))
            
            for semester in [2, 4, 6, 8]:  # Even semesters
                fixed_types = Config.get_fixed_slot_types_for_semester(semester)
                for fixed_type in fixed_types:
                    fixed_indices.update(Config.get_fixed_slot_indices(fixed_type, semester))
            
            # Add GE_LAB slots to fixed
            for year in [1, 2, 3, 4]:
                fixed_indices.update(Config.get_fixed_slot_indices("GE_LAB", year * 2 - 1))
            
            # Track latest slot used (excluding fixed slots)
            for t in range(len(self.time_slots)):
                if t not in fixed_indices:
                    classes_at_t = []
                    
                    for subject_id, time in variables['lecture'].keys():
                        if time == t:
                            classes_at_t.append(variables['lecture'][(subject_id, time)])
                    
                    for subject_id, time in variables['tutorial'].keys():
                        if time == t:
                            classes_at_t.append(variables['tutorial'][(subject_id, time)])
                    
                    for subject_id, time in variables['practical'].keys():
                        if time == t:
                            classes_at_t.append(variables['practical'][(subject_id, time)])
                    
                    if classes_at_t:
                        has_class = model.NewBoolVar(f"has_class_at_{t}")
                        model.Add(sum(classes_at_t) >= 1).OnlyEnforceIf(has_class)
                        model.Add(sum(classes_at_t) == 0).OnlyEnforceIf(has_class.Not())
                        
                        # If there's a class at t, max_used_slot >= t
                        model.Add(variables['max_used_slot'] >= t).OnlyEnforceIf(has_class)
                        
                        # Track which day is used
                        day_idx = t // len(self.slots)
                        model.Add(day_used[day_idx] == 1).OnlyEnforceIf(has_class)
            
            # Day penalty: prefer earlier days (Mon=0, Tue=1, ..., Sat=5)
            day_penalty = sum(
                day_used[day_idx] * day_idx * len(self.slots) * 2  # Higher weight for later days
                for day_idx in range(len(Config.DAYS))
            )
            
            # Slot penalty: prefer ending earlier in the day
            slot_penalty = variables['max_used_slot']
            
            # Combined objective
            model.Minimize(
                total_room_penalty + 
                ge_lecture_penalty + 
                total_practical_penalty + 
                day_penalty + 
                slot_penalty
            )
        else:
            # Without early completion: just minimize penalties
            model.Minimize(
                total_room_penalty + 
                ge_lecture_penalty + 
                total_practical_penalty
            )
    
    def _is_consecutive_slot(self, t: int) -> bool:
        """
        Check if time slot t is consecutive to t-1 (same day).
        
        Args:
            t: Time slot index
            
        Returns:
            True if t and t-1 are on the same day and consecutive
        """
        if t <= 0:
            return False
        
        day_idx_current = t // len(self.slots)
        slot_idx_current = t % len(self.slots)
        day_idx_prev = (t - 1) // len(self.slots)
        slot_idx_prev = (t - 1) % len(self.slots)
        
        return day_idx_current == day_idx_prev and slot_idx_current == slot_idx_prev + 1