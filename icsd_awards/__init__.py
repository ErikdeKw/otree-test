from otree.api import *
import csv
from pathlib import Path


doc = """
ICSD awards judging app
Single-file setup using assignments.csv
"""


class C(BaseConstants):
    NAME_IN_URL = 'icsd_awards'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 50


def _app_path(*parts):
    return Path(__file__).resolve().parent.joinpath(*parts)


def normalize_judge_code(value):
    return (value or '').strip().lower()


def read_assignments():
    path = _app_path('assignments.csv')
    rows = []
    with path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            rows.append(
                dict(
                    judge_code=normalize_judge_code(row.get('judge_code')),
                    judge_name=(row.get('judge_name') or '').strip(),
                    student_name=(row.get('student_name') or '').strip(),
                    student_id=((row.get('student_id') or '').strip() or (row.get('student_name') or '').strip()),
                    session_number=(row.get('session_number') or '').strip(),
                    format=(row.get('format') or '').strip(),  # NEW
                )
            )
    return rows


def judge_exists(judge_code):
    code = normalize_judge_code(judge_code)
    return any(r['judge_code'] == code for r in read_assignments())


def judge_name_for_code(judge_code):
    code = normalize_judge_code(judge_code)
    for r in read_assignments():
        if r['judge_code'] == code:
            return r['judge_name']
    return ''


def assignments_for_judge_code(judge_code):
    code = normalize_judge_code(judge_code)
    rows = [r for r in read_assignments() if r['judge_code'] == code]

    def sort_key(r):
        s = r.get('session_number', '')
        try:
            return (0, int(s))
        except:
            return (1, s)

    rows.sort(key=sort_key)

    cleaned = []
    for i, r in enumerate(rows, start=1):
        cleaned.append(
            dict(
                position=i,
                judge_code=r['judge_code'],
                judge_name=r['judge_name'],
                student_name=r['student_name'],
                student_id=r['student_id'],
                session_number=r['session_number'],
                format=r['format'],  # NEW
            )
        )
    return cleaned


class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


class Player(BasePlayer):
    judge_code = models.StringField(blank=True)
    selected_student_id_temp = models.StringField(blank=True)
    score = models.IntegerField(
        choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        widget=widgets.RadioSelectHorizontal,
        blank=True,
    )
    comments = models.LongStringField(blank=True)
    loaded_student_id = models.StringField(blank=True)
    go_back = models.BooleanField(initial=False, blank=True)


class JudgeRating(ExtraModel):
    player = models.Link(Player)
    judge_code = models.StringField()
    student_id = models.StringField()
    student_name = models.StringField(blank=True)
    session_number = models.StringField(blank=True)
    format = models.StringField(blank=True)  # NEW
    score = models.IntegerField(blank=True)
    comments = models.LongStringField(blank=True)


def get_current_judge_code(player: Player):
    return normalize_judge_code(player.participant.vars.get('judge_code', ''))


def get_selected_student_id(player: Player):
    return player.participant.vars.get('selected_student_id')


def set_selected_student_id(player: Player, student_id):
    player.participant.vars['selected_student_id'] = student_id


def clear_selected_student_id(player: Player):
    player.participant.vars['selected_student_id'] = None


def current_owner(player: Player):
    return player.in_round(1)


def rating_for_pair(player: Player, judge_code, student_id):
    judge_code = normalize_judge_code(judge_code)
    if not judge_code or not student_id:
        return None

    owner = current_owner(player)
    matches = JudgeRating.filter(player=owner, judge_code=judge_code, student_id=student_id)
    if matches:
        return matches[0]

    for p in player.session.get_participants():
        try:
            other_owner = p.get_players()[0]
        except:
            continue
        matches = JudgeRating.filter(player=other_owner, judge_code=judge_code, student_id=student_id)
        if matches:
            return matches[0]

    return None


def assignment_for_pair(player: Player, judge_code, student_id):
    judge_code = normalize_judge_code(judge_code)
    for a in assignments_for_judge_code(judge_code):
        if a['student_id'] == student_id:
            return a
    return None


def load_rating_into_player(player: Player):
    judge_code = get_current_judge_code(player)
    student_id = get_selected_student_id(player)

    if not judge_code or not student_id:
        return

    loaded_student_id = player.field_maybe_none('loaded_student_id')
    if loaded_student_id == student_id:
        return

    rating = rating_for_pair(player, judge_code, student_id)
    if rating:
        player.score = rating.score
        player.comments = rating.comments or ''
    else:
        player.score = None
        player.comments = ''

    player.loaded_student_id = student_id
    player.go_back = False


def save_rating(player: Player):
    judge_code = get_current_judge_code(player)
    student_id = get_selected_student_id(player)
    if not judge_code or not student_id:
        return

    assignment = assignment_for_pair(player, judge_code, student_id)
    if not assignment:
        return

    rating = rating_for_pair(player, judge_code, student_id)

    if rating:
        rating.judge_code = judge_code
        rating.student_name = assignment['student_name']
        rating.session_number = assignment.get('session_number', '')
        rating.format = assignment.get('format', '')  # NEW
        rating.score = player.field_maybe_none('score')
        rating.comments = player.comments or ''
    else:
        JudgeRating.create(
            player=current_owner(player),
            judge_code=judge_code,
            student_id=student_id,
            student_name=assignment['student_name'],
            session_number=assignment.get('session_number', ''),
            format=assignment.get('format', ''),  # NEW
            score=player.field_maybe_none('score'),
            comments=player.comments or '',
        )

    player.participant.vars['saved_message'] = f"Rating saved for {assignment['student_name']}."


class Login(Page):
    form_model = 'player'
    form_fields = ['judge_code']

    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == 1 and not get_current_judge_code(player)

    @staticmethod
    def error_message(player: Player, values):
        judge_code = normalize_judge_code(values.get('judge_code'))
        if not judge_exists(judge_code):
            return 'Unknown judge code.'

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        code = normalize_judge_code(player.judge_code)
        player.judge_code = code
        player.participant.vars['judge_code'] = code
        clear_selected_student_id(player)


class JudgeHome(Page):
    form_model = 'player'
    form_fields = ['selected_student_id_temp']

    @staticmethod
    def is_displayed(player: Player):
        if not get_current_judge_code(player):
            return False
        return not get_selected_student_id(player)

    @staticmethod
    def vars_for_template(player: Player):
        judge_code = get_current_judge_code(player)
        judge_name = judge_name_for_code(judge_code)
        saved_message = player.participant.vars.pop('saved_message', '')
        assignments = []

        for a in assignments_for_judge_code(judge_code):
            rating = rating_for_pair(player, judge_code, a['student_id'])
            assignments.append(
                dict(
                    position=a['position'],
                    student_name=a['student_name'],
                    student_id=a['student_id'],
                    session_number=a['session_number'],
                    format=a['format'],  # NEW
                    done=rating is not None,
                    score=rating.score if rating and rating.score is not None else '',
                    action_label='Edit' if rating else 'Open',
                )
            )

        return dict(
            judge_code=judge_code,
            judge_name=judge_name,
            saved_message=saved_message,
            assignments=assignments,
        )

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        student_id = (player.selected_student_id_temp or '').strip()
        if student_id:
            set_selected_student_id(player, student_id)
        player.selected_student_id_temp = ''


class RatePresentation(Page):
    form_model = 'player'
    form_fields = ['score', 'comments', 'go_back']

    @staticmethod
    def is_displayed(player: Player):
        if not get_current_judge_code(player):
            return False
        if not get_selected_student_id(player):
            return False
        load_rating_into_player(player)
        return True

    @staticmethod
    def vars_for_template(player: Player):
        judge_code = get_current_judge_code(player)
        student_id = get_selected_student_id(player)
        assignment = assignment_for_pair(player, judge_code, student_id) or {}
        return dict(
            student_name=assignment.get('student_name', ''),
            session_number=assignment.get('session_number', ''),
            format=assignment.get('format', ''),  # NEW
        )

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        going_back = bool(player.go_back)
        has_score = player.field_maybe_none('score') is not None
        has_comments = bool((player.comments or '').strip())

        if has_score or has_comments:
            save_rating(player)

        if going_back:
            clear_selected_student_id(player)
            player.loaded_student_id = ''

        player.go_back = False


page_sequence = [Login, JudgeHome, RatePresentation]


def custom_export(players):
    yield [
        'judge_code',
        'judge_name',
        'student_id',
        'student_name',
        'session_number',
        'format',  # NEW
        'score',
        'comments',
    ]

    for p in players:
        if p.round_number != 1:
            continue
        for r in JudgeRating.filter(player=p):
            yield [
                normalize_judge_code(r.judge_code),
                judge_name_for_code(r.judge_code),
                r.student_id,
                r.student_name,
                r.session_number,
                r.format,  # NEW
                r.score,
                r.comments,
            ]