"""
Solver engine module - UPDATED with room numbering
"""
from ortools.sat.python import cp_model
from src.config import Config
from typing import Dict, List, Any, Optional

class SolverEngine:
    def __init__(self, model: cp_model.CpModel, variables: Dict, subjects: List[Dict],
                 teacher_initials: Dict[str, str], teacher_preferences: Dict = None,
                 teacher_ranks: Dict[str, str] = None):
        self.model = model
        self.variables = variables
        self.subjects = subjects
        self.teacher_initials = teacher_initials
        self.teacher_preferences = teacher_preferences or {}
        # full_name -> rank (lowercase). Used for per-teacher caps.
        self.teacher_ranks = teacher_ranks or {}
        self.solver = cp_model.CpSolver()
        self.solution = None
        self.room_assignments = {}  # Track specific room assignments

    def _cap_for(self, teacher_full_name: str) -> int:
        rank = self.teacher_ranks.get(teacher_full_name, Config.DEFAULT_TEACHER_RANK)
        return Config.get_teacher_hour_cap(rank)

    def _get_event_id(self, subj: Dict) -> str:
        """
        Must mirror ConstraintBuilder exactly.
        """
        if subj.get("Merge_Group_ID"):
            return f"MERGE_{subj['Merge_Group_ID']}"
        return self._build_subject_id(subj)
 
    def _build_subject_id(self, subj: Dict) -> str:
        """
        Build consistent subject_id, handling split teaching with teacher initials.
        Must match the ID format used in constraint_builder.py
        """
        if subj.get("Is_Split_Teaching", False):
            teacher_initials = self.teacher_initials.get(subj["Teacher"], "UNK")
            return f"{subj['Course_Semester']}_{subj['Subject']}_{teacher_initials}"
        else:
            return f"{subj['Course_Semester']}_{subj['Subject']}"
        
    def solve(self) -> Optional[Dict]:
        """Solve the timetable optimization problem"""
        print(f"\n🔍 Starting solver (max {Config.SOLVER_TIME_LIMIT}s)...")
        
        self.solver.parameters.max_time_in_seconds = Config.SOLVER_TIME_LIMIT
        self.solver.parameters.log_search_progress = True
        
        status = self.solver.Solve(self.model)
        
        if status == cp_model.OPTIMAL:
            print("✅ OPTIMAL solution found!")
            self.solution = self._extract_solution()
            self.solution = self._assign_assistants(self.solution)  # NEW
            return self.solution
        elif status == cp_model.FEASIBLE:
            print("✅ FEASIBLE solution found!")
            self.solution = self._extract_solution()
            self.solution = self._assign_assistants(self.solution)  # NEW
            return self.solution
        else:
            print("❌ No solution found")
            self._diagnose_failure(status)
            return None

    def _assign_assistants(self, solution: Dict) -> Dict:
        """Post-processing: Assign assistant teachers to labs based on 1:20 ratio"""
        print("\n🔧 Assigning assistant teachers to lab classes...")
        
        teacher_availability = {}  # {teacher: {time_slot: is_free}}
        teacher_workload = {}      # {teacher: hours_assigned}
        
        # Collect all teachers
        all_teachers = set()
        for subj in self.subjects:
            all_teachers.add(subj["Teacher"])
            for co_teacher in subj.get("Co_Teachers", []):
                all_teachers.add(co_teacher)
        
        for teacher in all_teachers:
            teacher_workload[teacher] = 0
            teacher_availability[teacher] = {
                t: True for t in range(len(solution['time_slots']))
            }
        
        # Mark busy slots from scheduled classes
        for day, day_schedule in solution['master_schedule'].items():
            for slot, classes in day_schedule.items():
                time_idx = next(
                    (i for i, (d, s) in enumerate(solution['time_slots']) if d == day and s == slot),
                    None
                )
                if time_idx is None:
                    continue
                
                for class_info in classes:
                    for teacher in class_info['teachers_list']:
                        teacher_availability[teacher][time_idx] = False
                        teacher_workload[teacher] += 1
        
        assistant_assignments = {}  # {(event_id, time_idx): [assistants]}
        
        for subj in self.subjects:
            if subj["Practical_hours"] == 0:
                continue
            
            event_id = self._get_event_id(subj)
            student_count = subj["Students_count"]
            main_teacher = subj["Teacher"]
            department = subj["Department"]
            
            teachers_needed = (
                student_count + Config.LAB_TEACHER_RATIO - 1
            ) // Config.LAB_TEACHER_RATIO
            
            assistants_needed = teachers_needed - 1
            if assistants_needed <= 0:
                continue
            
            for day, day_schedule in solution['master_schedule'].items():
                for slot, classes in day_schedule.items():
                    for class_info in classes:
                        if (
                            class_info['subject'] == subj['Subject'] and
                            class_info['course_semester'] == subj['Course_Semester'] and
                            class_info['type'] == 'Practical' and
                            not class_info.get('is_continuation', False)
                        ):
                            start_time_idx = next(
                                (i for i, (d, s) in enumerate(solution['time_slots']) if d == day and s == slot),
                                None
                            )
                            if start_time_idx is None:
                                continue
                            
                            practical_hours = [start_time_idx, start_time_idx + 1]
                            
                            available_teachers = []
                            for teacher in all_teachers:
                                if teacher == main_teacher:
                                    continue
                                
                                teacher_dept = next(
                                    (s["Department"] for s in self.subjects if s["Teacher"] == teacher),
                                    None
                                )
                                if teacher_dept != department:
                                    continue
                                
                                if teacher_workload[teacher] >= self._cap_for(teacher):
                                    continue
                                
                                if all(teacher_availability[teacher].get(h, False) for h in practical_hours):
                                    available_teachers.append(teacher)
                            
                            available_teachers.sort(key=lambda t: teacher_workload[t])
                            
                            assigned = []
                            for teacher in available_teachers[:assistants_needed]:
                                assigned.append(teacher)
                                for h in practical_hours:
                                    teacher_availability[teacher][h] = False
                                teacher_workload[teacher] += 2
                            
                            assistant_assignments[(event_id, start_time_idx)] = assigned
                            
                            if len(assigned) < assistants_needed:
                                print(
                                    f"   ⚠️  {subj['Subject']} [{subj['Course_Semester']}]: "
                                    f"needs {teachers_needed} teachers, assigned {len(assigned) + 1}"
                                )
        
        solution['assistant_assignments'] = assistant_assignments
        solution['teacher_workload_after_assistants'] = teacher_workload
        return solution
    
    def _extract_solution(self) -> Dict:
        time_slots = Config.get_time_slots()
        slots = Config.get_slots_list()

        master_schedule = {}
        room_usage = {}

        # {(event_id, time_slot): [teachers]}
        teachers_at_slot = {}

        # ================================================================
        # FIRST PASS: determine which teachers are present at each event+slot
        # ================================================================
        for subj in self.subjects:
            event_id = self._get_event_id(subj)
            main_teacher = subj["Teacher"]

            for t in range(len(time_slots)):
                is_class_at_t = False

                if (event_id, t) in self.variables['lecture'] and self.solver.Value(self.variables['lecture'][(event_id, t)]) == 1:
                    is_class_at_t = True

                if (event_id, t) in self.variables['tutorial'] and self.solver.Value(self.variables['tutorial'][(event_id, t)]) == 1:
                    is_class_at_t = True

                if (event_id, t) in self.variables['practical'] and self.solver.Value(self.variables['practical'][(event_id, t)]) == 1:
                    is_class_at_t = True

                if is_class_at_t:
                    teachers = [main_teacher] + subj.get("Co_Teachers", [])
                    teachers_at_slot[(event_id, t)] = teachers

        # ================================================================
        # SECOND PASS: build master schedule
        # ================================================================

        # ---------------- LECTURES ----------------
        for (event_id, t), var in self.variables['lecture'].items():
            if self.solver.Value(var) == 1:
                day, slot = time_slots[t]
                subj_details = self._get_subject_details_by_event(event_id)

                teachers = teachers_at_slot.get((event_id, t), [subj_details["Teacher"]])
                teacher_str = ", ".join(teachers)

                assigned_room = "Room-TBD"
                for room in Config.get_rooms_by_type("classroom"):
                    if (event_id, t, room, 'lecture') in self.variables['room_assignment']:
                        if self.solver.Value(self.variables['room_assignment'][(event_id, t, room, 'lecture')]) == 1:
                            assigned_room = room
                            break

                if assigned_room == "Room-TBD":
                    for lab in [r for r, info in Config.ROOMS.items() if info["type"] == "lab"]:
                        if (event_id, t, lab, 'lecture') in self.variables['room_assignment']:
                            if self.solver.Value(self.variables['room_assignment'][(event_id, t, lab, 'lecture')]) == 1:
                                assigned_room = f"{lab} (Theory)"
                                break

                master_schedule.setdefault(day, {}).setdefault(slot, []).append({
                    'subject': subj_details['Subject'],
                    'teacher': teacher_str,
                    'teachers_list': teachers,
                    'course_semester': subj_details['Course_Semester'],
                    'type': 'Lecture',
                    'room': assigned_room,
                    'room_type': 'Classroom' if 'R-' in assigned_room else 'Lab',
                    'subject_type': subj_details['Subject_type'],
                    'section': subj_details['Section']
                })

        # ---------------- TUTORIALS ----------------
        for (event_id, t), var in self.variables['tutorial'].items():
            if self.solver.Value(var) == 1:
                day, slot = time_slots[t]
                subj_details = self._get_subject_details_by_event(event_id)

                teachers = teachers_at_slot.get((event_id, t), [subj_details["Teacher"]])
                teacher_str = ", ".join(teachers)

                assigned_room = "Room-TBD"
                for room in Config.get_rooms_by_type("classroom"):
                    if (event_id, t, room, 'tutorial') in self.variables['room_assignment']:
                        if self.solver.Value(self.variables['room_assignment'][(event_id, t, room, 'tutorial')]) == 1:
                            assigned_room = room
                            break

                if assigned_room == "Room-TBD":
                    for lab in [r for r, info in Config.ROOMS.items() if info["type"] == "lab"]:
                        if (event_id, t, lab, 'tutorial') in self.variables['room_assignment']:
                            if self.solver.Value(self.variables['room_assignment'][(event_id, t, lab, 'tutorial')]) == 1:
                                assigned_room = f"{lab} (Theory)"
                                break

                master_schedule.setdefault(day, {}).setdefault(slot, []).append({
                    'subject': subj_details['Subject'],
                    'teacher': teacher_str,
                    'teachers_list': teachers,
                    'course_semester': subj_details['Course_Semester'],
                    'type': 'Tutorial',
                    'room': assigned_room,
                    'room_type': 'Classroom' if 'R-' in assigned_room else 'Lab',
                    'subject_type': subj_details['Subject_type'],
                    'section': subj_details['Section']
                })

        # ---------------- PRACTICALS ----------------
        # Emit ONE entry per scheduled practical hour. Mark is_continuation when
        # the previous slot (same day) is also a scheduled practical for the same
        # event — that produces a clean two-entry pair for a 2-hour block and a
        # single entry for an isolated 1-hour practical.
        slots_per_day = len(slots)

        for (event_id, t), var in self.variables['practical'].items():
            if self.solver.Value(var) != 1:
                continue

            subj_details = self._get_subject_details_by_event(event_id)
            available_labs = Config.get_labs_by_department(subj_details["Department"])
            assigned_labs = [
                lab for lab in available_labs
                if (event_id, t, lab, 'practical') in self.variables['room_assignment']
                and self.solver.Value(
                    self.variables['room_assignment'][(event_id, t, lab, 'practical')]
                ) == 1
            ]
            room_name = ", ".join(assigned_labs) if assigned_labs else f"{subj_details['Lab_type']}-TBD"

            prev_t = t - 1
            is_continuation = (
                t > 0
                and prev_t // slots_per_day == t // slots_per_day
                and (event_id, prev_t) in self.variables['practical']
                and self.solver.Value(self.variables['practical'][(event_id, prev_t)]) == 1
            )

            day, slot = time_slots[t]
            teachers = teachers_at_slot.get((event_id, t), [subj_details["Teacher"]])

            master_schedule.setdefault(day, {}).setdefault(slot, []).append({
                'subject': subj_details['Subject'],
                'teacher': ", ".join(teachers),
                'teachers_list': teachers,
                'course_semester': subj_details['Course_Semester'],
                'type': 'Practical',
                'room': room_name,
                'room_type': subj_details['Lab_type'],
                'subject_type': subj_details['Subject_type'],
                'section': subj_details['Section'],
                'is_continuation': is_continuation
            })

        return {
            'master_schedule': master_schedule,
            'solver': self.solver,
            'variables': self.variables,
            'max_used_slot': self.solver.Value(self.variables['max_used_slot']),
            'time_slots': time_slots,
            'slots': slots,
            'room_assignments': room_usage
        }
    
    def _assign_room(self, time_slot: int, room_type: str, room_usage: Dict) -> int:
        """Assign a specific room number for a class"""
        if time_slot not in room_usage:
            room_usage[time_slot] = {}
        if room_type not in room_usage[time_slot]:
            room_usage[time_slot][room_type] = []
        
        # Get total rooms of this type
        if room_type == "Classroom":
            total_rooms = len(Config.get_rooms_by_type("classroom"))  # ✅ CORRECT
        else:
            # For labs, get count by department
            total_rooms = len([name for name, info in Config.ROOMS.items() 
                            if info["type"] == "lab"])  # ✅ CORRECT
        
        # Find next available room
        used_rooms = room_usage[time_slot][room_type]
        for room_num in range(1, total_rooms + 1):
            if room_num not in used_rooms:
                room_usage[time_slot][room_type].append(room_num)
                return room_num
        
        # If all rooms used, assign overflow (shouldn't happen with proper constraints)
        return total_rooms
    
    def _get_subject_details_by_event(self, event_id: str) -> Dict:
        """
        Returns representative subject details for an event.
        For merged events, returns the first matching subject.
        """
        if event_id.startswith("MERGE_"):
            merge_group_id = event_id.replace("MERGE_", "")
            for subj in self.subjects:
                if subj.get("Merge_Group_ID") == merge_group_id:
                    return subj
        else:
            for subj in self.subjects:
                if self._build_subject_id(subj) == event_id:
                    return subj

        return {}
 
    def _diagnose_failure(self, status: int):
        """Provide diagnostic information for failed solutions"""
        if status == cp_model.INFEASIBLE:
            print("\n💡 The problem is INFEASIBLE. Possible causes:")
            print("   - Too many hour requirements for available time slots")
            print("   - Teacher overload (>16 hours/week per teacher)")
            print("   - Insufficient rooms for concurrent classes")
            print("   - Fixed slot constraints too restrictive")
            print("   - Max consecutive/daily constraints too tight")
            print("   - Practical consecutive slot requirements cannot be met")
        elif status == cp_model.MODEL_INVALID:
            print("\n💡 The model is INVALID. Check constraint definitions.")
        elif status == cp_model.UNKNOWN:
            print("\n💡 Solver timed out or ran out of resources. Try:")
            print("   - Increasing solver time limit in config.py")
            print("   - Disabling some optional constraints")
            print("   - Reducing problem complexity")
    
    def print_summary(self):
        """Print solution summary statistics with before/after workload"""
        if not self.solution:
            print("\n❌ No solution available for summary")
            return
        
        print(f"\n📊 SOLUTION SUMMARY:")
        print("=" * 70)
        
        if self.solution['max_used_slot'] >= 0:
            latest_slot = self.solution['time_slots'][self.solution['max_used_slot']]
            print(f"   ⏰ Latest used time slot: {latest_slot}")
        
        # Count scheduled classes
        total_lectures = sum(
            self.solver.Value(var) for var in self.variables['lecture'].values()
        )
        total_tutorials = sum(
            self.solver.Value(var) for var in self.variables['tutorial'].values()
        )
        total_practicals = sum(
            self.solver.Value(var) for var in self.variables['practical'].values()
        )

        # Tutorials are hard-enforced via _add_hour_requirements; if a solution
        # exists, every required tutorial hour was scheduled.
        tutorials_total = len([s for s in self.subjects if s['Tutorial_hours'] > 0])

        print(f"\n   📚 Classes Scheduled:")
        print(f"      Lectures: {total_lectures}")
        print(f"      Tutorials: {total_tutorials} ({tutorials_total} subjects)")
        print(f"      Practicals: {total_practicals} sessions (×2 hours each)")
        print(f"      Total hours: {total_lectures + total_tutorials + (total_practicals * 2)}")
        
        # BEFORE/AFTER Teacher workload analysis
        print(f"\n   👨‍🏫 TEACHER WORKLOAD ANALYSIS:")
        print(f"   {'='*66}")
        
        # Calculate BEFORE workload (from input - what they're assigned to teach)
        teacher_hours_before = {}
        for subj in self.subjects:
            main_teacher = subj["Teacher"]
            taught_hours = subj.get("Total_taught_hours", subj["Total_hours"])
            
            if main_teacher not in teacher_hours_before:
                teacher_hours_before[main_teacher] = 0
            
            # For split teaching, divide hours
            if subj.get("Is_Split_Teaching", False) and subj.get("Co_Teachers"):
                num_teachers = 1 + len(subj["Co_Teachers"])
                teacher_hours_before[main_teacher] += taught_hours / num_teachers
                
                for co_teacher in subj["Co_Teachers"]:
                    if co_teacher not in teacher_hours_before:
                        teacher_hours_before[co_teacher] = 0
                    teacher_hours_before[co_teacher] += taught_hours / num_teachers
            else:
                teacher_hours_before[main_teacher] += taught_hours
                
                # Co-teaching: full hours for all
                for co_teacher in subj.get("Co_Teachers", []):
                    if co_teacher not in teacher_hours_before:
                        teacher_hours_before[co_teacher] = 0
                    teacher_hours_before[co_teacher] += taught_hours
        
        # Get AFTER workload (with assistant assignments)
        teacher_hours_after = self.solution.get('teacher_workload_after_assistants', {})
        
        # Display comparison — caps are per-teacher based on rank
        print(f"\n   {'Teacher':<30} {'Rank':<10} {'Before':<12} {'After':<12} {'Change':<10} {'Status'}")
        print(f"   {'-'*78}")

        all_teachers = sorted(set(list(teacher_hours_before.keys()) + list(teacher_hours_after.keys())))

        for teacher in all_teachers:
            before = teacher_hours_before.get(teacher, 0)
            after = teacher_hours_after.get(teacher, 0)
            change = after - before
            cap = self._cap_for(teacher)
            rank = self.teacher_ranks.get(teacher, Config.DEFAULT_TEACHER_RANK).title()

            # Status icon — compared against THIS teacher's cap
            if after > cap:
                status = "❌ OVER"
            elif after == cap:
                status = "✅ FULL"
            elif after >= cap * 0.9:
                status = "✅ NEAR"
            elif change > 0:
                status = "✅ +ASST"
            else:
                status = "✅ OK"

            change_str = f"+{change:.1f}h" if change > 0 else f"{change:.1f}h" if change < 0 else "—"

            print(f"   {teacher:<30} {rank:<10} {before:>5.1f}/{cap:<4}h  "
                  f"{after:>5.1f}/{cap:<4}h  {change_str:<10} {status}")

        print(f"   {'-'*78}")

        # Summary stats — each teacher counted against their own cap
        before_count = len([t for t, h in teacher_hours_before.items() if h > 0])
        after_full = sum(1 for t, h in teacher_hours_after.items() if h == self._cap_for(t))
        after_over = sum(1 for t, h in teacher_hours_after.items() if h > self._cap_for(t))
        after_under = sum(
            1 for t, h in teacher_hours_after.items()
            if 0 < h < self._cap_for(t)
        )
        assistants_added = len([t for t in all_teachers if teacher_hours_after.get(t, 0) > teacher_hours_before.get(t, 0)])
        
        print(f"\n   📈 Summary:")
        print(f"      Teachers with assignments: {before_count}")
        print(f"      At full rank-cap: {after_full}")
        print(f"      Over rank-cap: {after_over} {'❌' if after_over > 0 else ''}")
        print(f"      Under rank-cap: {after_under}")
        print(f"      Assigned as assistants: {assistants_added}")
        
        # Room utilization
        print(f"\n   🏢 Room Utilization:")
        room_usage = {}
        for day_schedule in self.solution['master_schedule'].values():
            for slot_classes in day_schedule.values():
                for class_info in slot_classes:
                    room = class_info['room']
                    room_usage[room] = room_usage.get(room, 0) + 1

        # Sort rooms properly
        def sort_room_key(room_name):
            parts = room_name.split('-')
            if len(parts) < 2:
                return (room_name, "", 0)
            
            room_type = parts[0]
            try:
                room_num = int(parts[-1].split()[0])  # Handle "Lab (Theory)"
                middle = parts[1] if len(parts) > 2 else ""
                return (room_type, middle, room_num)
            except (ValueError, IndexError):
                return (room_type, parts[1] if len(parts) > 1 else "", 0)

        for room in sorted(room_usage.keys(), key=sort_room_key):
            theory_marker = " (includes theory)" if "(Theory)" in room else ""
            print(f"      {room}: {room_usage[room]} slot-hours{theory_marker}")

        print("=" * 70)

        # Teacher preference satisfaction report (skipped if sheet was absent)
        self._print_teacher_preference_report()

    def _print_teacher_preference_report(self):
        """
        Per-teacher report on how well the solver respected the optional
        Teacher Preferences sheet. Anything that landed on an off day (or in
        an avoid window) is flagged as 'unavoidable' — the solver tried, but
        hard constraints (room/teacher/hour) blocked a better placement.
        """
        if not self.teacher_preferences or not self.solution:
            return

        from collections import defaultdict
        master_schedule = self.solution['master_schedule']
        slots_per_day = len(self.solution['slots'])
        # day_name list mirrors Config.DAYS index order
        day_names = Config.DAYS

        # full_name -> initials (reverse of teacher_initials)
        full_to_ini = self.teacher_initials

        per_teacher = defaultdict(lambda: {
            'classes': [],   # list of (day_idx, slot_idx_in_day)
        })
        for day, day_schedule in master_schedule.items():
            day_idx = day_names.index(day) if day in day_names else None
            if day_idx is None:
                continue
            for slot_str, classes in day_schedule.items():
                # Find slot index in the day
                try:
                    slot_idx = self.solution['slots'].index(slot_str)
                except ValueError:
                    continue
                for class_info in classes:
                    # 2-hour practical second halves get reported once via
                    # is_continuation flag; here we count every class-hour
                    # because penalties are applied per scheduled hour too.
                    for full_name in class_info.get('teachers_list', []):
                        ini = full_to_ini.get(full_name)
                        if ini and ini in self.teacher_preferences:
                            per_teacher[ini]['classes'].append((day_idx, slot_idx))

        print("\n" + "=" * 70)
        print("🧑‍🏫 TEACHER PREFERENCE REPORT")
        print("-" * 70)

        # Reverse map for nicer display: initials -> full name
        ini_to_full = {v: k for k, v in full_to_ini.items()}

        for ini in sorted(self.teacher_preferences.keys()):
            pref = self.teacher_preferences[ini]
            scheduled = per_teacher[ini]['classes']
            full_name = ini_to_full.get(ini, ini)
            total = len(scheduled)

            rank = self.teacher_ranks.get(full_name, Config.DEFAULT_TEACHER_RANK).title()
            cap = self._cap_for(full_name)
            header = f"{full_name} ({rank}, cap {cap}h):"

            if total == 0:
                print(f"   {header} no classes scheduled — preferences moot")
                continue

            off_days = set(pref.get('off_days', []))
            avoid_slots = set(pref.get('avoid_slots', []))
            preferred_slots = set(pref.get('preferred_slots', []))

            on_off_day = [(d, s) for d, s in scheduled if d in off_days]
            in_avoid = [(d, s) for d, s in scheduled
                        if d not in off_days and s in avoid_slots]
            in_pref = [(d, s) for d, s in scheduled
                       if d not in off_days and s not in avoid_slots and s in preferred_slots]

            satisfaction = (len(in_pref) / total) * 100 if preferred_slots else None
            sat_str = f" — satisfaction {satisfaction:.0f}%" if satisfaction is not None else ""

            print(f"\n   {header}  {total}h scheduled{sat_str}")
            if off_days:
                print(f"      Off-day classes:    {len(on_off_day):>2d} / {total} "
                      f"(prefers off: {sorted(day_names[d] for d in off_days)})")
                if on_off_day:
                    days_hit = sorted({day_names[d] for d, _ in on_off_day})
                    print(f"         ⚠️  unavoidable given hard constraints — solver "
                          f"couldn't move these off {', '.join(days_hit)}")
            if avoid_slots:
                avoid_label = self._slot_set_label(avoid_slots)
                print(f"      Avoid-time classes: {len(in_avoid):>2d} / {total} "
                      f"(avoids: {avoid_label})")
                if in_avoid:
                    print(f"         ⚠️  unavoidable given hard constraints — solver "
                          f"couldn't move these out of {avoid_label}")
            if preferred_slots:
                pref_label = self._slot_set_label(preferred_slots)
                print(f"      Preferred-time classes: {len(in_pref):>2d} / {total} "
                      f"(prefers: {pref_label})")

        print("=" * 70)

    @staticmethod
    def _slot_set_label(slot_idx_set):
        """Map a set of in-day slot indices back to a Morning/Afternoon/Evening label list."""
        labels = []
        for label, indices in Config.PREFERRED_TIME_SLOTS.items():
            if set(indices) == set(slot_idx_set):
                return label
            if set(indices).issubset(slot_idx_set):
                labels.append(label)
        return ", ".join(labels) if labels else f"slots {sorted(slot_idx_set)}"