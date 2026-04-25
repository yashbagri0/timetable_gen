"""
Timetable Generator - Main Entry Point (WITH PROFESSIONAL CONFIG MANAGEMENT)
"""
from src.data_loader import DataLoader
from src.constraint_builder import ConstraintBuilder
from src.solver_engine import SolverEngine
from src.pdf_generator import PDFGenerator
from src.excel_generator import ExcelGenerator
from src.feasibility_checker import FeasibilityChecker
from src.config import Config
from config_manager import ConfigManager, load_config_from_json_if_exists
import os
import sys
import argparse

def print_banner():
    """Print welcome banner"""
    print("\n" + "=" * 70)
    print(" " * 15 + "🎓 COLLEGE TIMETABLE GENERATOR 🎓")
    print(" " * 20 + "Advanced Constraint-Based System")
    print("=" * 70)
    print()

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Professional College Timetable Generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run automatically with saved config
  python main.py --interactive      # Step-by-step mode with confirmations
  python main.py --configure        # Configure constraint settings
  python main.py --show-config      # Display current configuration
  python main.py --semester even    # Override semester type
  python main.py -i -s odd          # Interactive mode with odd semester
        """
    )
    
    parser.add_argument(
        '--configure', '-c',
        action='store_true',
        help='Run interactive configuration wizard'
    )
    
    parser.add_argument(
        '--show-config', '-s',
        action='store_true',
        help='Display current configuration and exit'
    )
    
    parser.add_argument(
        '--semester',
        choices=['odd', 'even'],
        help='Override semester type (odd/even)'
    )
    
    parser.add_argument(
        '--config-file',
        default='config/timetable_config.yml',
        help='Path to configuration file (default: config/timetable_config.yml)'
    )
    
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Run in fully interactive mode (asks for confirmation at each step)'
    )
    
    return parser.parse_args()

class ConfigAdapter:
    """
    Adapter to make ConfigManager work with existing ConstraintBuilder
    This provides the same interface as the old ConstraintSelector
    """
    def __init__(self, config_manager: ConfigManager):
        self.config_mgr = config_manager
        self.selected_constraints = config_manager.get('constraints', {})
        self.max_consecutive_hours = config_manager.get('limits.max_consecutive_classes', 3)
        self.max_daily_hours_students = config_manager.get('limits.max_daily_hours', 6)
        self.max_daily_hours_teachers = config_manager.get('limits.max_daily_teacher_hours', 6)
    
    def is_enabled(self, constraint_key: str) -> bool:
        """Check if a constraint is enabled"""
        # Core constraints are always enabled
        if constraint_key in Config.CORE_CONSTRAINTS:
            return True
        return self.selected_constraints.get(constraint_key, True)
    
    def get_max_consecutive_hours(self) -> int:
        """Get maximum consecutive hours setting"""
        return self.max_consecutive_hours
    
    def get_max_daily_hours_students(self) -> int:
        """Get maximum daily hours for students"""
        return self.max_daily_hours_students
    
    def get_max_daily_hours_teachers(self) -> int:
        """Get maximum daily hours for teachers"""
        return self.max_daily_hours_teachers

def main():
    """Main function to run the timetable generator"""
    
    # Parse command line arguments
    args = parse_arguments()
    
    print_banner()
    
    # Load or migrate configuration
    config_mgr = load_config_from_json_if_exists()
    
    # Handle --show-config flag
    if args.show_config:
        config_mgr.print_current_config()
        return
    
    # Handle --configure flag
    if args.configure:
        config_mgr.interactive_configure()
        print("\n✅ Configuration updated! Run again without --configure to generate timetable.")
        return
    
    # Interactive mode: Ask for confirmation before each major step
    interactive = args.interactive
    
    # Override semester type if provided
    if args.semester:
        config_mgr.set('semester.type', args.semester)
        print(f"📅 Semester type overridden to: {args.semester.upper()}")
    
    # Interactive: Ask to review/change config
    if interactive:
        print("\n" + "=" * 70)
        print("🔧 INTERACTIVE MODE")
        print("=" * 70)
        config_mgr.print_current_config()
        
        while True:
            choice = input("\nDo you want to change configuration? (y/n) [n]: ").strip().lower()
            if choice == "" or choice == "n":
                break
            elif choice == "y":
                config_mgr.interactive_configure()
                break
            else:
                print("Invalid input. Enter 'y' or 'n'")
    
    # Step 1: Load and validate input data
    print("📋 STEP 1: DATA LOADING AND VALIDATION")
    print("-" * 70)
    
    # Create adapter for backward compatibility
    constraint_adapter = ConfigAdapter(config_mgr)
    
    # Pass semester type to data loader
    semester_type = config_mgr.get('semester.type', 'odd')
    
    data_loader = DataLoader("inputs/exceptions_input.xlsx")
    data_loader.semester_type = semester_type  # Set semester type before validation
    
    if not data_loader.validate_data():
        print("\n❌ Data validation failed. Please fix the issues and try again.")
        return
    
    if not data_loader.validate_config_match():
        print("\n❌ Config validation failed. Please update config.py with correct section counts.")
        return
    
    subjects = data_loader.get_subjects()
    teachers = data_loader.get_teachers()
    rooms = data_loader.get_rooms()
    course_semesters = data_loader.get_course_semesters()
    room_capacities = data_loader.get_room_capacities()
    
    # Print comprehensive data summary
    # data_loader.print_data_summary()
    
    # Interactive: Confirm before continuing
    if interactive:
        print("\n" + "=" * 70)
        while True:
            choice = input("Continue to feasibility check? (y/n) [y]: ").strip().lower()
            if choice == "" or choice == "y":
                break
            elif choice == "n":
                print("❌ Process stopped by user")
                return
            else:
                print("Invalid input. Enter 'y' or 'n'")
    
    # Step 1.1: PRE-SOLVER FEASIBILITY CHECK
    print("\n" + "=" * 70)
    print("📋 STEP 1.5: PRE-SOLVER FEASIBILITY CHECK")
    print("-" * 70)
    
    feasibility_checker = FeasibilityChecker(subjects, room_capacities)
    is_feasible, issues, warnings, stats = feasibility_checker.check_feasibility()
    # feasibility_checker.print_summary()
    
    if not is_feasible:
        print("\n" + "=" * 70)
        print("🛑 STOPPING: Critical issues found that prevent solution")
        print("=" * 70)
        print("\n💡 PLEASE FIX THE ISSUES ABOVE BEFORE PROCEEDING")
        print("   The solver will NOT find a solution with these problems.")
        print("\n🔧 If you need help, review the specific error messages above.")
        return
    
    # Interactive: Confirm before model building
    if interactive:
        print("\n" + "=" * 70)
        while True:
            choice = input("Continue to model building and solving? (y/n) [y]: ").strip().lower()
            if choice == "" or choice == "y":
                break
            elif choice == "n":
                print("❌ Process stopped by user")
                return
            else:
                print("Invalid input. Enter 'y' or 'n'")
    
    # Step 2: Display configuration being used
    print("\n" + "=" * 70)
    print("📋 STEP 2: USING CONFIGURATION")
    print("-" * 70)
    print(f"   📅 Semester Type: {semester_type.upper()}")
    print(f"   🔒 Constraints Enabled:")
    
    constraints_info = {
        'practical_consecutive': 'Practical Consecutive Slots',
        'max_consecutive_classes': 'Maximum Consecutive Classes',
        'max_daily_hours': 'Maximum Daily Hours (Students)',
        'max_daily_teacher_hours': 'Maximum Daily Hours (Teachers)',
        'early_completion': 'Early Completion Optimization'
    }
    
    for key, name in constraints_info.items():
        enabled = constraint_adapter.is_enabled(key)
        status = "✅" if enabled else "❌"
        print(f"      {status} {name}")
        
        if enabled and key == 'max_consecutive_classes':
            print(f"         → Limit: {constraint_adapter.get_max_consecutive_hours()} hours")
        elif enabled and key == 'max_daily_hours':
            print(f"         → Limit: {constraint_adapter.get_max_daily_hours_students()} hours/day")
        elif enabled and key == 'max_daily_teacher_hours':
            print(f"         → Limit: {constraint_adapter.get_max_daily_hours_teachers()} hours/day")
    
    print(f"\n   💡 To change settings, run: python main.py --configure")
    
    # Step 3: Build model with constraints
    print("\n" + "=" * 70)
    print("📋 STEP 3: MODEL BUILDING")
    print("-" * 70)
    
    constraint_builder = ConstraintBuilder(
        subjects, teachers, rooms, course_semesters, 
        room_capacities, constraint_adapter,
        data_loader.teacher_initials
    )
    model, variables = constraint_builder.build_model()
    
    # Step 4: Solve the model
    print("\n" + "=" * 70)
    print("📋 STEP 4: SOLVING OPTIMIZATION PROBLEM")
    print("-" * 70)
    
    solver_engine = SolverEngine(model, variables, subjects, data_loader.teacher_initials)
    solution = solver_engine.solve()
    
    if not solution:
        print("\n" + "=" * 70)
        print("❌ FAILED: No feasible solution found")
        print("=" * 70)
        print("\n💡 TROUBLESHOOTING TIPS:")
        print("   1. Review the pre-solver warnings above")
        print("   2. Try disabling some optional constraints:")
        print("      python main.py --configure")
        print("   3. Increase max consecutive/daily hours limits")
        print("   4. Check if practical consecutive constraint is too restrictive")
        print("   5. Review teacher workload distribution")
        print("\n🔧 Note: Pre-solver check passed but solver still failed.")
        print("   This might indicate:")
        print("   - Optional constraints are too restrictive")
        print("   - Edge case not caught by pre-solver checks")
        print("   - Early completion objective forcing impossible schedule")
        return
    
    # Step 5: Generate outputs
    print("\n" + "=" * 70)
    print("📋 STEP 5: GENERATING TIMETABLES")
    print("-" * 70)
    
    # Create output directory
    os.makedirs("output", exist_ok=True)
    
    # Generate Excel master timetable
    print("\n   📊 Generating master timetable (Excel)...")
    excel_generator = ExcelGenerator(solution, subjects)
    excel_generator.generate_master_timetable("output/master_timetable.xlsx")
    
    # Generate PDF timetables
    pdf_generator = PDFGenerator(solution, subjects, teachers, rooms, course_semesters)
    
    print("\n   📄 Generating teacher timetables (PDF)...")
    pdf_generator.generate_teacher_timetables("output/teachers/")
    
    print("\n   📄 Generating room timetables (PDF)...")
    pdf_generator.generate_room_timetables("output/rooms/")
    
    print("\n   📄 Generating course-semester timetables (PDF)...")
    pdf_generator.generate_course_semester_timetables("output/courses/")
    
    # Print summary
    solver_engine.print_summary()
    
    # Final success message
    print("\n" + "=" * 70)
    print("✅ SUCCESS: Timetable generation completed!")
    print("=" * 70)
    print("\n📁 OUTPUT FILES LOCATION:")
    print("   📂 output/")
    print("      ├── master_timetable.xlsx        (Complete schedule - Excel)")
    print("      ├── teachers/                    (Individual teacher schedules)")
    print("      ├── rooms/                       (Room utilization schedules)")
    print("      └── courses/                     (Course-semester schedules)")
    print("\n💡 KEY FEATURES:")
    print("   • Room numbers shown (Room-1, Lab-CS-1, etc.)")
    print("   • Reserved slots marked for GE/SEC/VAC/AEC")
    print("   • Continuous classes formatted without separators")
    print("   • Tutorial flexibility: sacrificed when needed")
    print("   • Year-appropriate reserved slot display")
    print("   • Multi-teacher support (co-teaching)")
    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n\n❌ An error occurred: {e}")
        import traceback
        traceback.print_exc()