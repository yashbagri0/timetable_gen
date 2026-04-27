"""
PDF generation — formal university-letterhead style timetables for teachers,
rooms, and course-semesters. A4 landscape, Helvetica throughout, color-coded
subject types, alternating row shading, and a footer key listing initials →
full names.
"""
import os
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from src.config import Config


class PDFGenerator:
    # ---- Palette ----------------------------------------------------------
    SUBJECT_COLORS = {
        'DSC': colors.HexColor('#D6E9F8'),  # light blue
        'DSE': colors.HexColor('#D9F0DC'),  # light green
        'GE':  colors.HexColor('#FFF6D5'),  # light yellow
        'SEC': colors.HexColor('#FFF6D5'),
        'VAC': colors.HexColor('#FFF6D5'),
        'AEC': colors.HexColor('#FFF6D5'),
    }
    PRACTICAL_COLOR = colors.HexColor('#FFE4CC')   # light orange overrides subject color for labs
    EMPTY_DAY_BG    = colors.HexColor('#EEEEEE')   # entire row when day has no classes
    BAND_BG         = colors.HexColor('#F7F7F7')   # alternating banding (only on day-label col)
    HEADER_BG       = colors.HexColor('#1F2A44')   # dark navy for grid header row
    HEADER_FG       = colors.white
    LOGO_BG         = colors.HexColor('#CCCCCC')
    BANNER_BG       = colors.white
    RULE_COLOR      = colors.black
    OUTER_BORDER    = colors.black
    INNER_BORDER    = colors.HexColor('#888888')

    # ---- Defaults ---------------------------------------------------------
    DEFAULT_COLLEGE_NAME    = "Your College Name"
    DEFAULT_DEPARTMENT      = "Computer Science"
    DEFAULT_ACADEMIC_YEAR   = f"{date.today().year}–{date.today().year + 1}"

    # ---- Slot ordering (matches Config.get_slots_list) --------------------
    # Pre-computed once for cell lookups: slot string -> in-day index 0..8
    @staticmethod
    def _slot_index_map() -> Dict[str, int]:
        return {s: i for i, s in enumerate(Config.get_slots_list())}

    def __init__(self, solution: Dict, subjects: List[Dict], teachers: List[str],
                 rooms: List[str], course_semesters: List[str],
                 teacher_ranks: Dict = None,
                 teacher_initials: Dict = None,
                 college_name: str = None,
                 department: str = None,
                 academic_year: str = None):
        self.solution = solution
        self.subjects = subjects
        self.teachers = teachers
        self.rooms = rooms
        self.course_semesters = course_semesters
        self.master_schedule = solution['master_schedule']
        self.slots = Config.get_slots_list()
        self.days = Config.DAYS
        self.assistant_assignments = solution.get('assistant_assignments', {})

        # full_name -> rank, full_name -> initials
        self.teacher_ranks = teacher_ranks or {}
        self.teacher_initials = teacher_initials or {}
        self._initials_to_name = {v: k for k, v in self.teacher_initials.items()}

        self.college_name  = college_name  or self.DEFAULT_COLLEGE_NAME
        self.department    = department    or self.DEFAULT_DEPARTMENT
        self.academic_year = academic_year or self.DEFAULT_ACADEMIC_YEAR
        self.generated_date = date.today().strftime('%d %B %Y')

        self._slot_idx = self._slot_index_map()
        self._para_styles = self._make_paragraph_styles()

    # ============================================================
    # Public API
    # ============================================================
    def generate_teacher_timetables(self, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        for teacher in self.teachers:
            grid, used_initials = self._build_grid(filter_fn=lambda c: teacher in c.get('teachers_list', []),
                                                   cell_format=self._format_cell_for_teacher_view)
            rank_lower = self.teacher_ranks.get(teacher, Config.DEFAULT_TEACHER_RANK)
            cap = Config.get_teacher_hour_cap(rank_lower)
            total_hours = self._count_scheduled_hours(grid)
            banner = (f"{teacher} ({rank_lower.title()})"
                      f" — {total_hours}h scheduled / {cap}h cap")
            filename = os.path.join(output_dir, f"{teacher.replace(' ', '_')}_timetable.pdf")
            print(f"      → {filename}")
            self._render_pdf(filename, "Teacher Timetable", banner, grid, used_initials)

    def generate_room_timetables(self, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        rooms_used = self._rooms_used_in_solution()
        for room in sorted(rooms_used, key=self._room_sort_key):
            grid, used_initials = self._build_grid(
                filter_fn=lambda c: self._class_uses_room(c, room),
                cell_format=self._format_cell_for_room_view,
            )
            banner = f"Room {room}"
            safe_name = room.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '')
            filename = os.path.join(output_dir, f"{safe_name}_timetable.pdf")
            print(f"      → {filename}")
            self._render_pdf(filename, "Room Timetable", banner, grid, used_initials)

    def generate_course_semester_timetables(self, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        for course_sem in sorted(set(self.course_semesters)):
            grid, used_initials = self._build_grid(
                filter_fn=lambda c: c.get('course_semester') == course_sem,
                cell_format=self._format_cell_for_course_view,
            )
            # Banner: humanize "B.Sc. (Hons) Computer Science-Sem7-A" -> Course/Semester/Section
            banner = self._humanize_course_sem(course_sem)
            safe_name = course_sem.replace(' ', '_').replace('/', '_').replace('.', '')[:80]
            filename = os.path.join(output_dir, f"{safe_name}_timetable.pdf")
            print(f"      → {filename}")
            self._render_pdf(filename, "Course Timetable", banner, grid, used_initials)

    # ============================================================
    # Grid construction (data + colors)
    # ============================================================
    def _build_grid(self, filter_fn, cell_format) -> Tuple[List[List[Dict]], set]:
        """
        Returns (grid, used_initials).
        grid is a 6×9 matrix of cell dicts:
            { 'content': Paragraph or '', 'subject_type': str, 'is_practical': bool }
        Empty cells have content='' and subject_type=None.
        used_initials is a set of teacher initials referenced anywhere in the grid.
        """
        grid: List[List[Dict]] = [
            [{'content': '', 'subject_type': None, 'is_practical': False}
             for _ in range(len(self.slots))]
            for _ in range(len(self.days))
        ]
        used_initials = set()

        for d_idx, day in enumerate(self.days):
            day_sched = self.master_schedule.get(day, {})
            for slot, classes in day_sched.items():
                if slot not in self._slot_idx:
                    continue
                s_idx = self._slot_idx[slot]
                # First class wins; if multiple, append "+N more" later.
                matching = [c for c in classes if filter_fn(c)]
                if not matching:
                    continue
                primary = matching[0]
                content_para = cell_format(primary, extra_count=len(matching) - 1)
                grid[d_idx][s_idx] = {
                    'content': content_para,
                    'subject_type': primary.get('subject_type', ''),
                    'is_practical': primary.get('type', '') == 'Practical',
                }
                # Collect initials for footer key
                for full_name in primary.get('teachers_list', [primary.get('teacher', '')]):
                    ini = self.teacher_initials.get(full_name)
                    if ini:
                        used_initials.add(ini)

        return grid, used_initials

    def _count_scheduled_hours(self, grid) -> int:
        """One entry per scheduled hour (matches solver_engine's per-hour extraction)."""
        return sum(1 for row in grid for cell in row if cell['content'])

    # ---- Cell formatters --------------------------------------------------
    def _format_cell_for_teacher_view(self, c: Dict, extra_count: int = 0) -> Paragraph:
        """Cell content for a Teacher PDF: subject + course-sem + room."""
        subject = c.get('subject', '?')
        room = c.get('room', '')
        course_sem = self._humanize_course_sem(c.get('course_semester', ''))
        section = c.get('section', '')
        kind = c.get('type', '')[:3].upper() if c.get('type') else ''
        meta_parts = []
        if course_sem: meta_parts.append(course_sem)
        if section:    meta_parts.append(f"Sec {section}")
        if room:       meta_parts.append(room)
        if kind:       meta_parts.append(kind)
        meta = " • ".join(meta_parts)
        if extra_count:
            meta += f" <font color='#AA0000'>+{extra_count} more</font>"
        return self._cell_paragraph(subject, meta)

    def _format_cell_for_room_view(self, c: Dict, extra_count: int = 0) -> Paragraph:
        """Cell content for a Room PDF: subject + teacher initials + course-sem."""
        subject = c.get('subject', '?')
        course_sem = self._humanize_course_sem(c.get('course_semester', ''))
        teachers_list = c.get('teachers_list', [c.get('teacher', '')])
        initials = ", ".join(self.teacher_initials.get(t, t.split()[-1][:3]) for t in teachers_list if t)
        kind = c.get('type', '')[:3].upper() if c.get('type') else ''
        meta_parts = []
        if initials:   meta_parts.append(initials)
        if course_sem: meta_parts.append(course_sem)
        if kind:       meta_parts.append(kind)
        meta = " • ".join(meta_parts)
        if extra_count:
            meta += f" <font color='#AA0000'>+{extra_count} more</font>"
        return self._cell_paragraph(subject, meta)

    def _format_cell_for_course_view(self, c: Dict, extra_count: int = 0) -> Paragraph:
        """Cell content for a Course-Semester PDF: subject + initials + room."""
        subject = c.get('subject', '?')
        room = c.get('room', '')
        teachers_list = c.get('teachers_list', [c.get('teacher', '')])
        initials = ", ".join(self.teacher_initials.get(t, t.split()[-1][:3]) for t in teachers_list if t)
        kind = c.get('type', '')[:3].upper() if c.get('type') else ''
        meta_parts = []
        if initials:   meta_parts.append(initials)
        if room:       meta_parts.append(room)
        if kind:       meta_parts.append(kind)
        meta = " • ".join(meta_parts)
        if extra_count:
            meta += f" <font color='#AA0000'>+{extra_count} more</font>"
        return self._cell_paragraph(subject, meta)

    def _cell_paragraph(self, subject: str, meta: str) -> Paragraph:
        text = (f"<b>{self._escape(subject)}</b>"
                f"<br/><font size='6.5'>{meta}</font>")
        return Paragraph(text, self._para_styles['cell'])

    # ============================================================
    # Page rendering
    # ============================================================
    def _render_pdf(self, filename: str, page_label: str, banner_text: str,
                    grid: List[List[Dict]], used_initials: set):
        doc = SimpleDocTemplate(
            filename,
            pagesize=landscape(A4),
            leftMargin=12 * mm, rightMargin=12 * mm,
            topMargin=10 * mm, bottomMargin=10 * mm,
        )
        story = []
        story.append(self._make_header(page_label))
        story.append(Spacer(1, 3 * mm))
        story.append(self._horizontal_rule())
        story.append(Spacer(1, 3 * mm))
        story.append(self._make_banner(banner_text))
        story.append(Spacer(1, 4 * mm))
        story.append(self._make_grid_table(grid))
        story.append(Spacer(1, 4 * mm))
        story.append(self._make_footer(used_initials))
        doc.build(story)

    # ---- Header (logo / college / type label) -----------------------------
    def _make_header(self, page_label: str) -> Table:
        ps = self._para_styles
        logo = Paragraph("<b>LOGO</b>", ps['logo_box'])
        college_block = (
            f"<b><font size='18'>{self._escape(self.college_name.upper())}</font></b>"
            f"<br/><font size='10'>"
            f"Department of {self._escape(self.department)} — Academic Year {self._escape(self.academic_year)}"
            f"</font>"
        )
        college = Paragraph(college_block, ps['college_block'])
        type_block = (
            f"<b><font size='12'>{self._escape(page_label)}</font></b>"
            f"<br/><font size='8'>Generated: {self._escape(self.generated_date)}</font>"
        )
        type_para = Paragraph(type_block, ps['type_label'])

        # Three-column layout: logo | center | type label
        tbl = Table(
            [[logo, college, type_para]],
            colWidths=[28 * mm, None, 55 * mm],
            rowHeights=[22 * mm],
        )
        tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',  (0, 0), (0, 0), 'CENTER'),
            ('ALIGN',  (1, 0), (1, 0), 'CENTER'),
            ('ALIGN',  (2, 0), (2, 0), 'RIGHT'),
            ('BACKGROUND', (0, 0), (0, 0), self.LOGO_BG),
            ('BOX', (0, 0), (0, 0), 0.75, colors.HexColor('#888888')),
            ('LEFTPADDING',  (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        return tbl

    def _horizontal_rule(self) -> Table:
        # Thick black rule via a 1-row, 1-cell table whose top border is heavy.
        rule = Table([['']], colWidths=['*'], rowHeights=[1])
        rule.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 1.5, self.RULE_COLOR),
        ]))
        return rule

    # ---- Banner -----------------------------------------------------------
    def _make_banner(self, text: str) -> Table:
        para = Paragraph(f"<b>{self._escape(text)}</b>", self._para_styles['banner'])
        tbl = Table([[para]], colWidths=['*'], rowHeights=[12 * mm])
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), self.BANNER_BG),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('LINEABOVE',  (0, 0), (-1, 0), 2, self.OUTER_BORDER),
            ('LINEBELOW',  (0, 0), (-1, 0), 2, self.OUTER_BORDER),
            ('TEXTCOLOR',  (0, 0), (-1, -1), colors.black),
        ]))
        return tbl

    # ---- Timetable grid ---------------------------------------------------
    def _make_grid_table(self, grid: List[List[Dict]]) -> Table:
        # Header row: 'Day' + 9 time slots
        header_row = [Paragraph("<b>Day</b>", self._para_styles['head'])]
        for s in self.slots:
            header_row.append(Paragraph(f"<b>{self._escape(s)}</b>", self._para_styles['head']))

        # Data rows
        data = [header_row]
        empty_rows = []   # row indices (in the table) that correspond to fully-empty days
        cell_bg_overrides = []  # list of (col, row, bg) for non-empty cells

        for d_idx, day in enumerate(self.days):
            row_cells = [Paragraph(f"<b>{day}</b>", self._para_styles['day_label'])]
            row_has_content = False
            for s_idx in range(len(self.slots)):
                cell = grid[d_idx][s_idx]
                row_cells.append(cell['content'] or '')
                if cell['content']:
                    row_has_content = True
                    bg = self.PRACTICAL_COLOR if cell['is_practical'] else \
                        self.SUBJECT_COLORS.get(cell['subject_type'], colors.white)
                    # +1 to col idx because col 0 is the day label
                    cell_bg_overrides.append((s_idx + 1, d_idx + 1, bg))
            if not row_has_content:
                empty_rows.append(d_idx + 1)
            data.append(row_cells)

        # Column widths: day label narrower than slot columns.
        # Landscape A4 usable ≈ 273mm; reserve ~20mm for day label, rest /9.
        col_widths = [20 * mm] + [(273 - 20) / len(self.slots) * mm] * len(self.slots)
        # Row heights tuned so header + banner + grid + footer all fit on one
        # A4-landscape page. Usable height ≈ 190mm; header≈22, banner≈12, grid
        # header≈8, 6 day rows × 18mm = 108, footer≈14, plus spacers ≈ 14mm.
        row_heights = [8 * mm] + [18 * mm] * len(self.days)

        tbl = Table(data, colWidths=col_widths, rowHeights=row_heights, repeatRows=1)

        ts = TableStyle([
            # Outer thick border
            ('BOX', (0, 0), (-1, -1), 1.4, self.OUTER_BORDER),
            # Inner thin grid
            ('INNERGRID', (0, 0), (-1, -1), 0.4, self.INNER_BORDER),
            # Header row styling
            ('BACKGROUND', (0, 0), (-1, 0), self.HEADER_BG),
            ('TEXTCOLOR',  (0, 0), (-1, 0), self.HEADER_FG),
            ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN',     (0, 0), (-1, 0), 'MIDDLE'),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            # Cell defaults
            ('VALIGN',  (0, 1), (-1, -1), 'TOP'),
            ('ALIGN',   (0, 1), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',  (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING',   (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ])

        # Day-label column alternating banding (rows are 1..6 in table coords)
        for r in range(1, len(self.days) + 1):
            if r % 2 == 0:
                ts.add('BACKGROUND', (0, r), (0, r), self.BAND_BG)

        # Per-cell subject color overrides (must be applied before empty-row override
        # so that an empty-day shading doesn't override a content cell — but content
        # cells live only on non-empty rows, so order is moot).
        for col, row, bg in cell_bg_overrides:
            ts.add('BACKGROUND', (col, row), (col, row), bg)

        # Fully-empty rows: shade the whole row (incl. day label) with EMPTY_DAY_BG
        for r in empty_rows:
            ts.add('BACKGROUND', (0, r), (-1, r), self.EMPTY_DAY_BG)

        tbl.setStyle(ts)
        return tbl

    # ---- Footer -----------------------------------------------------------
    def _make_footer(self, used_initials: set) -> Table:
        # Initials → full name key, plus a generated-on/college line.
        if used_initials:
            mapping_pairs = sorted(used_initials)
            entries = []
            for ini in mapping_pairs:
                full = self._initials_to_name.get(ini, '?')
                entries.append(f"<b>{self._escape(ini)}</b>: {self._escape(full)}")
            mapping_text = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(entries)
        else:
            mapping_text = "<i>No teachers scheduled.</i>"

        title = Paragraph("<b>Initials Key</b>", self._para_styles['footer_label'])
        body  = Paragraph(mapping_text, self._para_styles['footer_body'])

        tbl = Table([[title], [body]], colWidths=['*'])
        tbl.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.6, colors.HexColor('#666666')),
            ('LEFTPADDING',  (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING',   (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ]))
        return tbl

    # ============================================================
    # Helpers
    # ============================================================
    def _make_paragraph_styles(self) -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        normal = base['Normal']
        return {
            'cell': ParagraphStyle(
                'cell', parent=normal, fontName='Helvetica',
                fontSize=8, leading=10, alignment=TA_LEFT, textColor=colors.black,
            ),
            'head': ParagraphStyle(
                'head', parent=normal, fontName='Helvetica-Bold',
                fontSize=8, leading=10, alignment=TA_CENTER, textColor=self.HEADER_FG,
            ),
            'day_label': ParagraphStyle(
                'day_label', parent=normal, fontName='Helvetica-Bold',
                fontSize=10, leading=12, alignment=TA_CENTER, textColor=colors.black,
            ),
            'logo_box': ParagraphStyle(
                'logo_box', parent=normal, fontName='Helvetica-Bold',
                fontSize=14, leading=18, alignment=TA_CENTER, textColor=colors.HexColor('#666666'),
            ),
            'college_block': ParagraphStyle(
                'college_block', parent=normal, fontName='Helvetica',
                alignment=TA_CENTER, textColor=colors.black, leading=14,
            ),
            'type_label': ParagraphStyle(
                'type_label', parent=normal, fontName='Helvetica',
                alignment=TA_RIGHT, textColor=colors.black, leading=14,
            ),
            'banner': ParagraphStyle(
                'banner', parent=normal, fontName='Helvetica-Bold',
                fontSize=14, leading=16, alignment=TA_CENTER, textColor=colors.black,
            ),
            'footer_label': ParagraphStyle(
                'footer_label', parent=normal, fontName='Helvetica-Bold',
                fontSize=8, leading=10, alignment=TA_LEFT,
            ),
            'footer_body': ParagraphStyle(
                'footer_body', parent=normal, fontName='Helvetica',
                fontSize=7.5, leading=10, alignment=TA_LEFT,
            ),
        }

    def _humanize_course_sem(self, course_sem: str) -> str:
        # Best-effort: "B.Sc. (Hons) Computer Science-Sem3-A" -> nicer
        # COMMON-GE-Sem1-X-SecA -> "GE Sem 1 (Sec A)"
        if not course_sem:
            return ""
        if course_sem.startswith("COMMON-"):
            # COMMON-{TYPE}-Sem{N}-{name}-Sec{X}
            parts = course_sem.split('-')
            if len(parts) >= 4:
                stype = parts[1]
                sem = parts[2].replace('Sem', 'Sem ')
                section = parts[-1].replace('Sec', 'Sec ') if parts[-1].startswith('Sec') else ''
                return f"{stype} {sem}" + (f" ({section})" if section else "")
            return course_sem
        # Course-SemN-X
        return course_sem.replace('-Sem', ' • Sem ')

    def _rooms_used_in_solution(self) -> set:
        used = set()
        for day_sched in self.master_schedule.values():
            for classes in day_sched.values():
                for c in classes:
                    room = c.get('room', '')
                    if not room or room.endswith('-TBD'):
                        continue
                    if ',' in room:
                        used.update(r.strip() for r in room.split(','))
                    else:
                        used.add(room)
        return used

    def _class_uses_room(self, class_info: Dict, room: str) -> bool:
        cell_room = class_info.get('room', '')
        if cell_room == room:
            return True
        # Multi-room (e.g., merged practicals using multiple labs): "CL-1, CL-2"
        if ',' in cell_room and room in [r.strip() for r in cell_room.split(',')]:
            return True
        return False

    @staticmethod
    def _room_sort_key(room_name: str):
        # Stable sort: split into (prefix, number)
        parts = room_name.split('-')
        if len(parts) >= 2 and parts[-1].split()[0].isdigit():
            return (parts[0], int(parts[-1].split()[0]))
        return (room_name, 0)

    @staticmethod
    def _escape(text: str) -> str:
        # Minimal Paragraph-text escaping
        if text is None:
            return ""
        return (str(text)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))
