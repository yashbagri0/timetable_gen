"""
Pre-solver feasibility checker
Validates input data and predicts infeasibility BEFORE calling solver
"""
from src.config import Config
from typing import List, Dict, Tuple
from collections import defaultdict

class FeasibilityChecker:
    def __init__(self, subjects: List[Dict], room_capacities: Dict, teacher_ranks: Dict = None):
        self.subjects = subjects
        self.room_capacities = room_capacities
        # full_name -> rank (lowercase). Missing names fall back to default.
        self.teacher_ranks = teacher_ranks or {}
        self.issues = []
        self.warnings = []
        self.stats = {}
        
    def check_feasibility(self) -> Tuple[bool, List[str], List[str], Dict]:
        """
        Comprehensive feasibility check
        Returns: (is_feasible, critical_issues, warnings, statistics)
        """
        print("\n🔍 PRE-SOLVER FEASIBILITY CHECK")
        print("=" * 70)
        
        # Run all checks. _check_vac_slot_availability runs first so that a
        # subject in a year whose fixed slots aren't configured is reported
        # with a clear message before any other (less specific) issue piles
        # on top of it.
        self._check_vac_slot_availability()
        self._check_teacher_workload()
        self._check_fixed_slot_capacity()
        self._check_room_capacity()
        self._check_practical_slots()
        self._check_room_penalty_bounds()
        self._calculate_statistics()
        
        # Determine feasibility
        is_feasible = len(self.issues) == 0
        
        return is_feasible, self.issues, self.warnings, self.stats
    
    def _check_teacher_workload(self):
        """Check if any teacher exceeds maximum hours"""
        print("\n📊 Checking Teacher Workload...")
        
        # Use same counting logic as data_loader
        teacher_loads = {}
        processed_merge_groups = set()
        
        for subj in self.subjects:
            # Check if merged course
            is_merged = subj.get("Is_Merged", False)
            merge_group_id = subj.get("Merge_Group_ID")
            
            # Skip if already counted this merge group
            if is_merged and merge_group_id in processed_merge_groups:
                continue
            
            if is_merged and merge_group_id:
                processed_merge_groups.add(merge_group_id)
            
            # Get main teacher hours
            main_teacher = subj["Teacher"]
            main_hours = subj.get("Taught_Lecture_hours", 0) + subj.get("Taught_Tutorial_hours", 0) + subj.get("Taught_Practical_hours", 0)
            
            if main_hours == 0:
                main_hours = subj.get("Total_taught_hours", subj["Total_hours"])
            
            if main_teacher not in teacher_loads:
                teacher_loads[main_teacher] = {"total": 0, "subjects": []}
            
            teacher_loads[main_teacher]["total"] += main_hours
            teacher_loads[main_teacher]["subjects"].append({
                "subject": subj["Subject"],
                "hours": main_hours,
                "course_sem": subj["Course_Semester"],
                "split": subj.get("Is_Split_Teaching", False)
            })
            
            # Handle co-teachers (skip split teaching - they have their own entries)
            for co_teacher in subj.get("Co_Teachers", []):
                if subj.get("Is_Split_Teaching", False):
                    continue
                
                if co_teacher not in teacher_loads:
                    teacher_loads[co_teacher] = {"total": 0, "subjects": []}
                
                teacher_loads[co_teacher]["total"] += main_hours
                teacher_loads[co_teacher]["subjects"].append({
                    "subject": subj["Subject"],
                    "hours": main_hours,
                    "course_sem": subj["Course_Semester"],
                    "split": False
                })
        
        # Display results — cap is per-teacher based on rank
        overloaded_teachers = []
        for teacher, data in sorted(teacher_loads.items(), key=lambda x: x[1]["total"], reverse=True):
            rank = self.teacher_ranks.get(teacher, Config.DEFAULT_TEACHER_RANK)
            cap = Config.get_teacher_hour_cap(rank)
            rank_label = rank.title()

            if data["total"] > cap:
                overloaded_teachers.append((teacher, data["total"], data["subjects"], rank_label, cap))
                self.issues.append(
                    f"❌ TEACHER OVERLOAD: {teacher} ({rank_label}) has "
                    f"{data['total']:.1f} hours (cap: {cap} hours for {rank_label})"
                )
                print(f"   ❌ {teacher} ({rank_label}, cap {cap}h): {data['total']:.1f}/{cap} hours")
                print(f"      Subjects:")
                for s in data["subjects"]:
                    split_note = " (split)" if s.get("split") else ""
                    print(f"        - {s['subject']} [{s['course_sem']}]: {s['hours']:.1f}h{split_note}")
            elif data["total"] >= cap * 0.9:
                # 90-100% is GOOD (near optimal), not a warning!
                print(f"   ✅ {teacher} ({rank_label}, cap {cap}h): {data['total']:.1f}/{cap} hours (near optimal)")
            elif data["total"] < cap * 0.8:
                self.warnings.append(
                    f"⚠️  {teacher} ({rank_label}) underutilized: "
                    f"{data['total']:.1f}/{cap} hours (could take more)"
                )
                print(f"   ⚠️  {teacher} ({rank_label}, cap {cap}h): {data['total']:.1f}/{cap} hours (underutilized)")
            else:
                print(f"   ✅ {teacher} ({rank_label}, cap {cap}h): {data['total']:.1f}/{cap} hours")

        self.stats["teacher_loads"] = dict(teacher_loads)

        if overloaded_teachers:
            print(f"\n   💡 SOLUTION: Reassign subjects from overloaded teachers, "
                  f"upgrade their rank, or adjust Config.TEACHER_RANK_HOUR_CAPS.")
    
    def _check_fixed_slot_capacity(self):
        """Check if GE/SEC/VAC/AEC subjects fit in their fixed slots"""
        print("\n📊 Checking Fixed Slot Capacity...")
        
        # Calculate capacity for each fixed slot type
        fixed_slot_usage = {}
        
        for slot_type in ["GE", "SEC", "VAC", "AEC"]:
            # Count subjects of this type (accounting for merged courses)
            subjects_of_type = [s for s in self.subjects if s["Subject_type"] == slot_type]
            
            if len(subjects_of_type) == 0:
                continue
            
            # Calculate hours needed (count merged courses once)
            processed_merge_groups = set()
            lecture_hours = 0
            tutorial_hours = 0
            practical_sessions = 0
            
            for s in subjects_of_type:
                is_merged = s.get("Is_Merged", False)
                merge_group_id = s.get("Merge_Group_ID")
                
                if is_merged and merge_group_id in processed_merge_groups:
                    continue
                
                if is_merged and merge_group_id:
                    processed_merge_groups.add(merge_group_id)
                
                lecture_hours += s["Lecture_hours"]
                tutorial_hours += s["Tutorial_hours"]
                practical_sessions += s["Practical_hours"] // 2
            
            total_needed = lecture_hours + tutorial_hours + practical_sessions
            
            # Get slot indices - need to aggregate across all years for SEC/VAC
            if slot_type in ["SEC", "VAC"]:
                # For SEC/VAC, we need to aggregate slots from all subjects' semesters
                all_slot_indices = set()
                for subject in subjects_of_type:
                    semester = subject["Semester"]
                    slot_indices = Config.get_fixed_slot_indices(slot_type, semester)
                    all_slot_indices.update(slot_indices)
                slot_indices = list(all_slot_indices)
                available_hours = len(slot_indices)
            else:
                # For GE/AEC, get slots directly
                slot_indices = Config.get_fixed_slot_indices(slot_type)
                available_hours = len(slot_indices)
            
            # Calculate available capacity (considering multiple rooms)
            classroom_capacity = self.room_capacities.get("Classroom", {}).get("count", 10)
            
            # Each fixed slot time can accommodate multiple classes in different rooms
            total_capacity = available_hours * classroom_capacity
            
            fixed_slot_usage[slot_type] = {
                "subjects": len(subjects_of_type),
                "hours_needed": total_needed,
                "slots_available": available_hours,
                "capacity": total_capacity,
                "utilization": (total_needed / total_capacity * 100) if total_capacity > 0 else 0
            }
            
            print(f"\n   {slot_type}:")
            print(f"      Subjects: {len(subjects_of_type)}")
            print(f"      Hours needed: {total_needed}")
            print(f"      Time slots available: {available_hours}")
            print(f"      Room capacity: {classroom_capacity} classrooms")
            print(f"      Total capacity: {total_capacity} class-hours")
            
            if total_capacity > 0:
                print(f"      Utilization: {fixed_slot_usage[slot_type]['utilization']:.1f}%")
                
                if total_needed > total_capacity:
                    self.issues.append(
                        f"❌ {slot_type} OVERFLOW: Need {total_needed} hours, "
                        f"capacity is {total_capacity} class-hours"
                    )
                    print(f"      ❌ NOT ENOUGH CAPACITY!")
                    print(f"      💡 SOLUTION: Reduce {slot_type} subjects or add more {slot_type} time slots")
                elif fixed_slot_usage[slot_type]['utilization'] > 80:
                    self.warnings.append(
                        f"⚠️  {slot_type} at {fixed_slot_usage[slot_type]['utilization']:.1f}% capacity"
                    )
                    print(f"      ⚠️  High utilization")
                else:
                    print(f"      ✅ Sufficient capacity")
            else:
                # No capacity available
                self.issues.append(
                    f"❌ {slot_type} NO SLOTS CONFIGURED: Need {total_needed} hours but no time slots defined"
                )
                print(f"      ❌ NO TIME SLOTS CONFIGURED!")
                print(f"      💡 SOLUTION: Add {slot_type} time slots in config.py FIXED_SLOTS")
        
        self.stats["fixed_slot_usage"] = fixed_slot_usage
    
    def _check_room_capacity(self):
        """Check if there are enough rooms for concurrent classes"""
        print("\n📊 Checking Room Capacity...")
        
        # Count DSC/DSE subjects by type
        dsc_dse_subjects = [s for s in self.subjects if s["Subject_type"] in ["DSC", "DSE", ""]]
        
        total_lectures = sum(s["Lecture_hours"] for s in dsc_dse_subjects)
        total_tutorials = sum(s["Tutorial_hours"] for s in dsc_dse_subjects)
        total_practicals = sum(s["Practical_hours"] // 2 for s in dsc_dse_subjects)
        
        # Calculate available non-fixed slots
        total_slots = len(Config.get_time_slots())
        fixed_slots = len(Config.get_all_fixed_slot_indices())
        available_slots = total_slots - fixed_slots
        
        # Calculate capacities
        classroom_count = self.room_capacities.get("Classroom", {}).get("count", 10)
        classroom_capacity = available_slots * classroom_count
        
        # Count actual labs from Config.ROOMS
        lab_count = sum(1 for room_info in Config.ROOMS.values() if room_info["type"] == "lab")
        lab_capacity = available_slots * lab_count if lab_count > 0 else 0
        
        theory_needed = total_lectures + total_tutorials
        practical_needed = total_practicals
        
        print(f"\n   Theory Classes (DSC/DSE):")
        print(f"      Hours needed: {theory_needed}")
        print(f"      Available slots: {available_slots} (excluding fixed)")
        print(f"      Classroom count: {classroom_count}")
        print(f"      Total capacity: {classroom_capacity} class-hours")
        
        if classroom_capacity > 0:
            print(f"      Utilization: {(theory_needed/classroom_capacity*100):.1f}%")
            
            if theory_needed > classroom_capacity:
                self.issues.append(
                    f"❌ CLASSROOM SHORTAGE: Need {theory_needed} hours, "
                    f"capacity is {classroom_capacity} class-hours"
                )
                print(f"      ❌ NOT ENOUGH CLASSROOMS!")
            elif theory_needed / classroom_capacity > 0.8:
                self.warnings.append(f"⚠️  Classroom utilization at {(theory_needed/classroom_capacity*100):.1f}%")
                print(f"      ⚠️  High classroom utilization")
            else:
                print(f"      ✅ Sufficient classrooms")
        
        print(f"\n   Practical Classes:")
        print(f"      Sessions needed: {practical_needed}")
        print(f"      Available slots: {available_slots}")
        print(f"      Lab count: {lab_count}")
        
        if lab_capacity > 0:
            print(f"      Lab capacity: {lab_capacity} lab-hours")
            print(f"      Utilization: {(practical_needed/lab_capacity*100):.1f}%")
            
            if practical_needed > lab_capacity:
                self.issues.append(
                    f"❌ LAB SHORTAGE: Need {practical_needed} sessions, "
                    f"capacity is {lab_capacity} lab-hours"
                )
                print(f"      ❌ NOT ENOUGH LABS!")
            elif practical_needed / lab_capacity > 0.8:
                self.warnings.append(f"⚠️  Lab utilization at {(practical_needed/lab_capacity*100):.1f}%")
                print(f"      ⚠️  High lab utilization")
            else:
                print(f"      ✅ Sufficient labs")
        else:
            if practical_needed > 0:
                self.issues.append(f"❌ NO LABS CONFIGURED: Need {practical_needed} sessions but no labs defined")
                print(f"      ❌ NO LABS CONFIGURED!")
            else:
                print(f"      ℹ️  No practicals needed")
        
        self.stats["room_usage"] = {
            "theory_needed": theory_needed,
            "theory_capacity": classroom_capacity,
            "practical_needed": practical_needed,
            "practical_capacity": lab_capacity
        }
    
    def _check_practical_slots(self):
        """Check if there are enough consecutive slots for practicals"""
        print("\n📊 Checking Practical Consecutive Slots...")
        
        # Count practicals
        practical_subjects = [s for s in self.subjects if s["Practical_hours"] > 0]
        total_practical_sessions = sum(s["Practical_hours"] // 2 for s in practical_subjects)
        
        # Calculate available consecutive pairs (avoiding fixed slots)
        slots_per_day = len(Config.get_slots_list())
        fixed_indices = set(Config.get_all_fixed_slot_indices())
        
        available_pairs = 0
        for day_idx in range(len(Config.DAYS)):
            for slot_idx in range(slots_per_day - 1):
                t1 = day_idx * slots_per_day + slot_idx
                t2 = t1 + 1
                
                # Check if both slots are free (not in fixed slots)
                if t1 not in fixed_indices and t2 not in fixed_indices:
                    available_pairs += 1
        
        # Count actual labs from Config.ROOMS (type == "lab")
        lab_count = sum(1 for room_info in Config.ROOMS.values() if room_info["type"] == "lab")
        
        total_pair_capacity = available_pairs * lab_count if lab_count > 0 else 0
        
        print(f"      Practical sessions needed: {total_practical_sessions}")
        print(f"      Consecutive pairs per lab: {available_pairs}")
        print(f"      Number of labs: {lab_count}")
        
        if total_pair_capacity > 0:
            print(f"      Total capacity: {total_pair_capacity} sessions")
            print(f"      Utilization: {(total_practical_sessions/total_pair_capacity*100):.1f}%")
            
            if total_practical_sessions > total_pair_capacity:
                self.issues.append(
                    f"❌ PRACTICAL SLOT SHORTAGE: Need {total_practical_sessions} sessions, "
                    f"capacity is {total_pair_capacity}"
                )
                print(f"      ❌ NOT ENOUGH CONSECUTIVE SLOTS!")
            elif total_practical_sessions / total_pair_capacity > 0.8:
                self.warnings.append(
                    f"⚠️  Practical slots at {(total_practical_sessions/total_pair_capacity*100):.1f}% capacity"
                )
                print(f"      ⚠️  High utilization")
            else:
                print(f"      ✅ Sufficient consecutive slots")
        else:
            # No labs or no capacity
            if total_practical_sessions > 0:
                if lab_count == 0:
                    self.issues.append(
                        f"❌ NO LABS DEFINED: Need {total_practical_sessions} practical sessions but no labs configured"
                    )
                    print(f"      ❌ NO LABS CONFIGURED!")
                else:
                    self.issues.append(
                        f"❌ NO AVAILABLE CONSECUTIVE SLOTS: All slots blocked by fixed slots"
                    )
                    print(f"      ❌ NO CONSECUTIVE SLOTS AVAILABLE!")
            else:
                print(f"      ℹ️  No practical sessions needed")
        
        self.stats["practical_slots"] = {
            "needed": total_practical_sessions,
            "capacity": total_pair_capacity
        }
    
    def _check_room_penalty_bounds(self):
        """
        Catch the case where a class's student count is so far from any candidate
        room/lab capacity that the resulting penalty would exceed the bound on
        the room_penalty IntVar — a structural infeasibility the solver detects
        only at presolve as 'linear: never in domain'.

        Mirrors the bound math in ConstraintBuilder._add_room_fit_penalties and
        _add_lab_fit_penalties so a violation here predicts a UNSAT model.
        """
        print("\n📊 Checking Room Penalty Bounds (penalty IntVar overflow)...")

        bound = Config.PENALTY_VAR_MAX
        w_under = Config.PENALTY_WEIGHTS["undersized_room"]
        w_over = Config.PENALTY_WEIGHTS["oversized_room"]

        # Build per-department lab list once
        labs_by_dept = {
            dept: [
                (name, info) for name, info in Config.ROOMS.items()
                if info["type"] == "lab" and info.get("department") == dept
            ]
            for dept in {s["Department"] for s in self.subjects}
        }
        classrooms = [
            (name, info) for name, info in Config.ROOMS.items()
            if info["type"] == "classroom"
        ]

        violations_lab = []
        violations_room = []

        for s in self.subjects:
            students = s.get("Students_count", 0)
            if students <= 0:
                continue

            # ---- Practical / lab side -----------------------------------------
            if s.get("Practical_hours", 0) > 0:
                dept_labs = labs_by_dept.get(s["Department"], [])
                if dept_labs:
                    # Per _add_lab_fit_penalties: cap range = [cap_max - 3, cap_max + 3]
                    min_overflow = min(
                        max(0, students - (info["capacity_max"] + 3))
                        for _, info in dept_labs
                    )
                    if min_overflow * w_under > bound:
                        violations_lab.append(
                            (s, students, dept_labs, min_overflow, min_overflow * w_under)
                        )

            # ---- Lecture / classroom side -------------------------------------
            if s.get("Lecture_hours", 0) > 0 or s.get("Tutorial_hours", 0) > 0:
                # Pick the best (smallest non-zero) room overflow OR oversized
                best_under = min(
                    max(0, students - info["capacity_max"]) for _, info in classrooms
                )
                best_over = min(
                    max(0, info["capacity_min"] - students) for _, info in classrooms
                )
                penalty = max(best_under * w_under, best_over * w_over)
                if penalty > bound:
                    violations_room.append((s, students, penalty))

        if not violations_lab and not violations_room:
            print(f"   ✅ All room/lab penalties stay within IntVar bound ({bound:,})")
            return

        for s, students, dept_labs, overflow, pen in violations_lab:
            cap_max = max(info["capacity_max"] for _, info in dept_labs)
            self.issues.append(
                f"❌ LAB OVERFLOW: '{s['Subject']}' [{s['Course_Semester']}] has "
                f"{students} students, but the largest available {s['Department']} lab "
                f"holds only {cap_max} (+3 tolerance). Min overflow {overflow} × penalty "
                f"weight {w_under} = {pen:,}, which exceeds the room_penalty IntVar bound "
                f"of {bound:,}. The solver will return INFEASIBLE at presolve "
                f"('linear: never in domain'). Fix: split the section, add a larger lab, "
                f"or raise Config.PENALTY_VAR_MAX above {pen:,}."
            )
            print(f"   ❌ {s['Subject']} [{s['Course_Semester']}]: {students} students vs "
                  f"max lab cap {cap_max}+3 → penalty {pen:,} > bound {bound:,}")

        for s, students, pen in violations_room:
            self.issues.append(
                f"❌ ROOM PENALTY OVERFLOW: '{s['Subject']}' [{s['Course_Semester']}] "
                f"with {students} students would incur penalty {pen:,} > IntVar bound "
                f"{bound:,}. Solver will fail at presolve. Fix: adjust class size, add "
                f"appropriately-sized rooms, or raise Config.PENALTY_VAR_MAX."
            )
            print(f"   ❌ {s['Subject']} [{s['Course_Semester']}]: {students} students → "
                  f"penalty {pen:,} > bound {bound:,}")

    def _calculate_statistics(self):
        """Calculate overall statistics"""
        # Total hours
        total_hours = sum(s["Total_hours"] for s in self.subjects)
        
        # By type
        by_type = defaultdict(lambda: {"count": 0, "hours": 0})
        for s in self.subjects:
            stype = s["Subject_type"] if s["Subject_type"] else "DSC/DSE"
            by_type[stype]["count"] += 1
            by_type[stype]["hours"] += s["Total_hours"]
        
        self.stats["overview"] = {
            "total_subjects": len(self.subjects),
            "total_hours": total_hours,
            "by_type": dict(by_type)
        }

    def _check_vac_slot_availability(self):
        """
        For every fixed-slot subject (VAC/GE/SEC/AEC), confirm Config has at
        least one allowed time slot for its semester. Otherwise the constraint
        builder would later raise inside _add_hour_requirements — surfacing
        the failure here keeps the frontend progress bar lighting up the
        Feasibility Check (Step 2) red, rather than the deeper Build-Model
        (Step 3) which is much harder to diagnose.

        Mirrors the slot-resolution code in ConstraintBuilder
        ._get_allowed_slots_for_subject() so the two stay in sync.
        """
        print("\n📊 Checking Fixed-Slot Availability (VAC/GE/SEC/AEC)...")
        fixed_slot_types = ("VAC", "GE", "SEC", "AEC")
        violations = 0

        for s in self.subjects:
            stype = s.get("Subject_type")
            if stype not in fixed_slot_types:
                continue
            sem = s.get("Semester")
            if sem is None:
                continue

            # Config.get_fixed_slot_indices ignores `semester` for GE/AEC
            # (those are universal across years) and uses it for VAC/SEC.
            allowed = Config.get_fixed_slot_indices(stype, sem)
            if allowed:
                continue

            violations += 1
            cs = s.get("Course_Semester") or f"{stype} Sem{sem}"
            subj_name = s.get("Subject") or "(unnamed)"
            self.issues.append(
                f"❌ {stype} SLOT ERROR: '{subj_name}' [{cs}] has no allowed "
                f"time slots configured for Semester {sem}. "
                f"VAC/SEC/GE/AEC subjects are only supported for Semesters 1–4. "
                f"Either remove this subject or add slot configuration for "
                f"Sem{sem} in Config.FIXED_SLOTS."
            )
            print(f"   ❌ {stype} '{subj_name}' [{cs}]: 0 slots for Sem{sem}")

        if violations == 0:
            print("   ✅ All fixed-slot subjects have configured slots")

    def print_summary(self):
        """Print summary of feasibility check"""
        print("\n" + "=" * 70)
        print("FEASIBILITY CHECK SUMMARY")
        print("=" * 70)
        
        if len(self.issues) == 0:
            print("\n✅ ALL CHECKS PASSED - Input appears feasible")
            print("   Proceeding to solver...")
        else:
            print(f"\n❌ FOUND {len(self.issues)} CRITICAL ISSUE(S)")
            print("\nCRITICAL ISSUES THAT PREVENT SOLUTION:")
            for issue in self.issues:
                print(f"   {issue}")
            
            print("\n💡 RECOMMENDATIONS:")
            print("   Fix these issues before running the solver.")
            print("   The solver will NOT find a solution with these problems.")
        
        if len(self.warnings) > 0:
            print(f"\n⚠️  {len(self.warnings)} WARNING(S):")
            for warning in self.warnings:
                print(f"   {warning}")
        
        print("\n" + "=" * 70)