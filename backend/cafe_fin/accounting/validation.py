"""Schema-bound, exact values. The UI never decides monetary validity."""

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from cafe_fin.core.amounts import checked_int64, parse_money
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError

KINDS = {'text', 'date', 'integer', 'decimal', 'money', 'choice', 'formula'}


def normalize_schema(columns, semantics, previous=()):
    if not isinstance(columns, list) or len(columns) > 256:
        raise CoreError('SCHEMA_INVALID', 'Sổ hỗ trợ tối đa 256 cột.')
    old = {c['id']: dict(c, logical_index=c.get('logical_index', i)) for i, c in enumerate(previous)}
    seen, result = set(), []
    next_index = max((c.get('logical_index', i) for i, c in enumerate(previous)), default=-1) + 1
    for col in columns:
        if not isinstance(col, dict) or not isinstance(col.get('id'), str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', col['id']):
            raise CoreError('COLUMN_ID_INVALID', 'ID cột cần ổn định, bắt đầu bằng chữ, tối đa 64 ký tự.')
        identity = col['id']
        if identity in seen or not isinstance(col.get('kind'), str) or col['kind'] not in KINDS or not isinstance(col.get('name'), str) or not 1 <= len(col['name']) <= 120:
            raise CoreError('SCHEMA_INVALID', 'Cột trùng, thiếu tên hoặc kiểu không được hỗ trợ.')
        seen.add(identity)
        kind = col['kind']
        scale = 2 if kind == 'money' else 0 if kind == 'integer' else col.get('scale', 2)
        precision = col.get('precision', 18)
        if type(scale) is not int or not 0 <= scale <= 9 or type(precision) is not int or not scale <= precision <= 19:
            raise CoreError('SCHEMA_PRECISION_INVALID', 'Precision tối đa 19 và scale tối đa 9; tiền VND scale 2.')
        choices = col.get('choices', [])
        if not isinstance(choices, list) or len(choices) > 500 or any(not isinstance(x, str) or len(x) > 256 for x in choices):
            raise CoreError('SCHEMA_CHOICES_INVALID', 'Danh sách lựa chọn không hợp lệ.')
        rules = col.get('validation', {})
        if not isinstance(rules, dict) or set(rules) - {'min', 'max', 'max_length'}:
            raise CoreError('SCHEMA_VALIDATION_INVALID', 'Quy tắc hỗ trợ min, max và max_length.')
        for key in ('min', 'max'):
            if key in rules:
                try:
                    if not isinstance(rules[key], str) or not Decimal(rules[key]).is_finite():
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise CoreError('SCHEMA_VALIDATION_INVALID', 'Giới hạn số phải là chuỗi Decimal.') from None
        if 'min' in rules and 'max' in rules and Decimal(rules['min']) > Decimal(rules['max']):
            raise CoreError('SCHEMA_VALIDATION_INVALID', 'Giới hạn nhỏ nhất phải không lớn hơn giới hạn lớn nhất.')
        if 'max_length' in rules and (type(rules['max_length']) is not int or not 1 <= rules['max_length'] <= 32767):
            raise CoreError('SCHEMA_VALIDATION_INVALID', 'max_length cần từ 1 đến 32767.')
        if any(key in col and type(col[key]) is not bool for key in ('required', 'editable')):
            raise CoreError('SCHEMA_INVALID', 'required và editable phải là boolean.')
        logical_index = old[identity]['logical_index'] if identity in old else next_index
        if identity not in old:
            next_index += 1
        result.append(dict(col, scale=scale, precision=precision, required=bool(col.get('required', False)),
            editable=bool(col.get('editable', kind != 'formula')), choices=choices,
            validation=rules, logical_index=logical_index))
    if not isinstance(semantics, dict):
        raise CoreError('SEMANTICS_INVALID', 'Cấu hình báo cáo không hợp lệ.')
    scalar_refs = ('date_column', 'income_column', 'expense_column', 'amount_column', 'direction_column', 'currency_column')
    for key in scalar_refs:
        if semantics.get(key) is not None and (not isinstance(semantics[key], str) or semantics[key] not in seen):
            raise CoreError('SEMANTICS_COLUMN_MISSING', 'Cột ánh xạ báo cáo không tồn tại.')
    for key in ('group_columns', 'duplicate_columns', 'business_key_columns'):
        refs = semantics.get(key, [])
        if not isinstance(refs, list) or any(not isinstance(c, str) or c not in seen for c in refs):
            raise CoreError('SEMANTICS_COLUMN_MISSING', 'Cột nhóm/so trùng không tồn tại.')
    if semantics.get('currency', 'VND') != 'VND':
        raise CoreError('CURRENCY_UNSUPPORTED', 'Core Money hiện chỉ hỗ trợ VND; có thể ghi đơn vị khác ở cột text mà không cộng tiền.')
    return result, semantics


def number_string(value, profile):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise CoreError('INVALID_DECIMAL', 'Số cần giá trị thập phân chính xác; không dùng float.')
    if not isinstance(profile, dict):
        raise CoreError('NUMBER_PROFILE_INVALID', 'Profile số phải là cấu hình có cấu trúc.')
    if isinstance(value, int) and abs(value) >= 10 ** 64:
        raise CoreError('INVALID_DECIMAL', 'Giá trị số quá dài.')
    if isinstance(value, Decimal) and (not value.is_finite() or
            len(value.as_tuple().digits) > 64 or abs(value.as_tuple().exponent) > 64):
        raise CoreError('INVALID_DECIMAL', 'Số Decimal không hữu hạn hoặc vượt giới hạn độ dài.')
    text = str(value).strip()
    if len(text) > 64:
        raise CoreError('INVALID_DECIMAL', 'Giá trị số quá dài.')
    decimal = profile.get('decimal_separator', '.')
    thousands = profile.get('thousands_separator', '')
    if decimal not in ('.', ',') or thousands not in ('', ',', '.', ' ') or decimal == thousands:
        raise CoreError('NUMBER_PROFILE_INVALID', 'Chọn riêng dấu thập phân và phân nhóm.')
    # Native exact values already have canonical numeric semantics. Locale is
    # solely an interpretation rule for source text, never for authoritative data.
    if isinstance(value, (int, Decimal)):
        if isinstance(value, Decimal) and not value.is_finite():
            raise CoreError('INVALID_DECIMAL', 'Số phải là Decimal hữu hạn.')
        text = format(value, 'f') if isinstance(value, Decimal) else str(value)
        if len(text) > 64:
            raise CoreError('INVALID_DECIMAL', 'Giá trị số quá dài.')
        return text
    if thousands:
        signless = text.lstrip('-')
        parts = signless.split(decimal)
        integral = parts[0]
        if len(parts) > 1 and any(thousands in part for part in parts[1:]):
            raise CoreError('INVALID_GROUPING', 'Không đặt dấu phân nhóm trong phần thập phân.')
        if thousands in integral and not re.fullmatch(r'\d{1,3}(?:' + re.escape(thousands) + r'\d{3})+', integral):
            raise CoreError('INVALID_GROUPING', 'Dấu phân nhóm phải chia đúng nhóm ba chữ số.')
        text = text.replace(thousands, '')
    text = text.replace(decimal, '.')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        raise CoreError('INVALID_DECIMAL', 'Số không khớp dấu thập phân/phân nhóm của profile.')
    return text


def normalize_value(value, column, profile=None, date_meta=None):
    profile = profile or {}
    if value is None or value == '':
        if column.get('required'):
            raise CoreError('REQUIRED', 'Ô bắt buộc chưa có giá trị.')
        return None, None
    kind = column['kind']
    if kind in ('text', 'choice'):
        if not isinstance(value, str):
            value = str(value)
        if len(value) > column.get('validation', {}).get('max_length', 32767):
            raise CoreError('TEXT_TOO_LONG', 'Nội dung ô vượt giới hạn độ dài.')
        if column.get('pad_width'):
            width = column['pad_width']
            if type(width) is not int or not 1 <= width <= 256:
                raise CoreError('PADDING_INVALID', 'Quy tắc đệm mã không hợp lệ.')
            value = value.zfill(width)
        if kind == 'choice' and value not in column['choices']:
            raise CoreError('CHOICE_INVALID', 'Giá trị chưa có trong danh sách lựa chọn.')
        return value, None
    if kind == 'date':
        try:
            if date_meta and date_meta.get('excel_serial') is not None:
                if date_meta.get('epoch', '1900') not in ('1900', '1904'):
                    raise CoreError('DATE_EPOCH_INVALID', 'Chỉ hỗ trợ Excel epoch 1900 hoặc 1904.')
                days = Decimal(str(date_meta['excel_serial']))
                if days != days.to_integral_value() or not 0 <= days <= 2958465:
                    raise ValueError()
                serial = int(days)
                if date_meta.get('epoch') == '1904':
                    parsed = date(1904, 1, 1) + timedelta(days=serial)
                else:
                    if serial == 60:
                        raise CoreError('EXCEL_INVALID_DATE', 'Excel serial 60 là ngày 29/02/1900 không tồn tại.')
                    parsed = date(1899, 12, 31) + timedelta(days=serial - (1 if serial > 60 else 0))
            elif isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                parsed = date.fromisoformat(value)
            else:
                if not isinstance(profile.get('date_format'), str) or not profile['date_format']:
                    raise CoreError('DATE_FORMAT_REQUIRED', 'Chọn định dạng ngày trong profile; không tự đoán ngày mơ hồ.')
                parsed = datetime.strptime(str(value), profile['date_format']).date()
            return parsed.isoformat(), None
        except (ValueError, OverflowError, InvalidOperation):
            raise CoreError('DATE_INVALID', 'Ngày không hợp lệ hoặc không khớp profile.') from None
    with localcontext() as ctx:
        ctx.prec = 80
        text = number_string(value, profile)
        number = Decimal(text)
        scale = column.get('scale', 2)
        scaled = number * 10 ** scale
        if scaled != scaled.to_integral_value():
            raise CoreError('EXCESS_PRECISION', f'Chỉ hỗ trợ tối đa {scale} chữ số lẻ; không tự làm tròn.')
        integer = parse_money(format(number, 'f')) if kind == 'money' else checked_int64(int(scaled))
        if len(str(abs(int(scaled)))) > column.get('precision', 18):
            raise CoreError('PRECISION_EXCEEDED', 'Giá trị vượt precision của cột.')
        for op, test in (('min', lambda x: number < x), ('max', lambda x: number > x)):
            bound = column.get('validation', {}).get(op)
            if bound is not None and test(Decimal(bound)):
                raise CoreError('VALUE_OUT_OF_RANGE', 'Giá trị nằm ngoài giới hạn của cột.')
        return format(number, f'.{scale}f'), integer


def fingerprint(values, columns=None):
    # Column IDs/types are part of canonical identity; null/text/Decimal do not collide.
    selected = sorted(values) if columns is None else columns
    if not selected:
        return None
    return hashlib.sha256(canonical_json(['accounting-fingerprint-v1', [(c, values.get(c)) for c in selected]]).encode()).hexdigest()


def safe_export_text(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + value
    return value
