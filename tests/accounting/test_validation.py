"""Exact schema/value boundaries using synthetic, local accounting inputs."""

from decimal import Decimal

import pytest
from cafe_fin.accounting.formulas import FormulaEngine, LiteralCell
from cafe_fin.accounting.validation import (
    fingerprint,
    normalize_schema,
    normalize_value,
    number_string,
    safe_export_text,
)
from cafe_fin.core.amounts import INT64_MAX, INT64_MIN
from cafe_fin.core.errors import CoreError


def column(kind='text', **overrides):
    columns, _ = normalize_schema([dict(id='code', name='Mã hàng', kind=kind, **overrides)], {})
    return columns[0]


def error(code, callback, *args, **kwargs):
    with pytest.raises(CoreError) as failure:
        callback(*args, **kwargs)
    assert failure.value.code == code
    assert failure.value.message


def test_schema_rename_and_display_reorder_preserve_stable_mapping_and_logical_positions():
    original = [dict(id='day', name='Ngày', kind='date'),
                dict(id='income', name='Thu', kind='money'),
                dict(id='code', name='Mã hàng', kind='text')]
    semantics = dict(date_column='day', income_column='income', duplicate_columns=['day', 'code'],
                     business_key_columns=['code'], group_columns=['code'])
    previous, _ = normalize_schema(original, semantics)
    mapping = {'income': 'E', 'day': 'A', 'code': 'C'}
    revised, mapped = normalize_schema([
        original[2] | {'name': 'Mã sản phẩm mới', 'logical_index': 999},
        original[0] | {'name': 'Ngày ghi sổ'}, original[1],
        dict(id='note', name='Ghi chú', kind='text', logical_index=0),
    ], semantics, previous)
    assert [c['id'] for c in revised] == ['code', 'day', 'income', 'note']
    assert {c['id']: c['logical_index'] for c in revised} == {'day': 0, 'income': 1, 'code': 2, 'note': 3}
    assert mapped == semantics
    assert mapping == {'income': 'E', 'day': 'A', 'code': 'C'}
    assert mapping[revised[0]['id']] == 'C'
    assert previous[2]['name'] == 'Mã hàng'  # No mutation of prior schema revision.


def test_previous_schema_without_logical_indexes_uses_prior_logical_order():
    previous = [dict(id='first', name='Cột A', kind='text'),
                dict(id='second', name='Cột B', kind='text')]
    revised, _ = normalize_schema(list(reversed(previous)), {}, previous)
    assert [(c['id'], c['logical_index']) for c in revised] == [('second', 1), ('first', 0)]


def test_new_logical_index_follows_largest_prior_position_instead_of_display_length():
    previous = [dict(id='kept', name='Cột giữ', kind='text', logical_index=7)]
    revised, _ = normalize_schema(previous + [dict(id='new', name='Cột mới', kind='text')], {}, previous)
    assert [c['logical_index'] for c in revised] == [7, 8]


def test_schema_defaults_preserve_core_money_and_integer_scales():
    assert column('money', scale=9)['scale'] == 2
    assert column('integer', scale=7)['scale'] == 0
    assert column('formula')['editable'] is False
    assert column('text')['editable'] is True
    assert column('decimal', scale=3, precision=19)['precision'] == 19


@pytest.mark.parametrize('malformed,code', [
    (None, 'COLUMN_ID_INVALID'),
    ({'id': None, 'name': 'A', 'kind': 'text'}, 'COLUMN_ID_INVALID'),
    ({'id': 1, 'name': 'A', 'kind': 'text'}, 'COLUMN_ID_INVALID'),
    ({'id': '1bad', 'name': 'A', 'kind': 'text'}, 'COLUMN_ID_INVALID'),
    ({'id': 'bad-id', 'name': 'A', 'kind': 'text'}, 'COLUMN_ID_INVALID'),
    ({'id': 'a' * 65, 'name': 'A', 'kind': 'text'}, 'COLUMN_ID_INVALID'),
    ({'id': 'ok', 'name': '', 'kind': 'text'}, 'SCHEMA_INVALID'),
    ({'id': 'ok', 'name': 'A', 'kind': 'float'}, 'SCHEMA_INVALID'),
    ({'id': 'ok', 'name': 'A', 'kind': []}, 'SCHEMA_INVALID'),
    ({'id': 'ok', 'name': 'A', 'kind': 'text', 'required': 'false'}, 'SCHEMA_INVALID'),
    ({'id': 'ok', 'name': 'A', 'kind': 'text', 'editable': 0}, 'SCHEMA_INVALID'),
])
def test_schema_rejects_malformed_or_unstable_column_ids_and_types(malformed, code):
    error(code, normalize_schema, [malformed], {})


@pytest.mark.parametrize('override,code', [
    ({'scale': 10}, 'SCHEMA_PRECISION_INVALID'),
    ({'scale': -1}, 'SCHEMA_PRECISION_INVALID'),
    ({'precision': 20}, 'SCHEMA_PRECISION_INVALID'),
    ({'scale': 3, 'precision': 2}, 'SCHEMA_PRECISION_INVALID'),
    ({'scale': True}, 'SCHEMA_PRECISION_INVALID'),
    ({'choices': [1]}, 'SCHEMA_CHOICES_INVALID'),
    ({'choices': ['a'] * 501}, 'SCHEMA_CHOICES_INVALID'),
    ({'validation': {'regex': '.*'}}, 'SCHEMA_VALIDATION_INVALID'),
    ({'validation': {'min': 1}}, 'SCHEMA_VALIDATION_INVALID'),
    ({'validation': {'min': 'NaN'}}, 'SCHEMA_VALIDATION_INVALID'),
    ({'validation': {'max': 'Infinity'}}, 'SCHEMA_VALIDATION_INVALID'),
    ({'validation': {'min': '3', 'max': '2'}}, 'SCHEMA_VALIDATION_INVALID'),
    ({'validation': {'max_length': 0}}, 'SCHEMA_VALIDATION_INVALID'),
])
def test_schema_precision_choices_and_validation_are_checked(override, code):
    error(code, column, 'decimal', **override)


@pytest.mark.parametrize('semantics,code', [
    ([], 'SEMANTICS_INVALID'),
    ({'income_column': 'Mã hàng'}, 'SEMANTICS_COLUMN_MISSING'),
    ({'date_column': ['code']}, 'SEMANTICS_COLUMN_MISSING'),
    ({'group_columns': [['code']]}, 'SEMANTICS_COLUMN_MISSING'),
    ({'duplicate_columns': 'code'}, 'SEMANTICS_COLUMN_MISSING'),
    ({'business_key_columns': ['missing']}, 'SEMANTICS_COLUMN_MISSING'),
    ({'currency': 'USD'}, 'CURRENCY_UNSUPPORTED'),
])
def test_mapping_semantics_reference_stable_ids_and_supported_currency(semantics, code):
    error(code, normalize_schema, [dict(id='code', name='Mã hàng', kind='text')], semantics)


def test_schema_rejects_duplicate_ids_and_column_resource_limit():
    duplicate = dict(id='same', name='Mã', kind='text')
    error('SCHEMA_INVALID', normalize_schema, [duplicate, duplicate], {})
    error('SCHEMA_INVALID', normalize_schema, [duplicate] * 257, {})


@pytest.mark.parametrize('raw,profile,expected', [
    ('1,234.56', {'decimal_separator': '.', 'thousands_separator': ','}, '1234.56'),
    ('-1.234,56', {'decimal_separator': ',', 'thousands_separator': '.'}, '-1234.56'),
    ('1 234 567,89', {'decimal_separator': ',', 'thousands_separator': ' '}, '1234567.89'),
    ('1234,56', {'decimal_separator': ','}, '1234.56'),
    ('  -0.25  ', {}, '-0.25'),
    (Decimal('1234.56'), {'decimal_separator': ',', 'thousands_separator': '.'}, '1234.56'),
    (Decimal('1E+3'), {'decimal_separator': ','}, '1000'),
    (1234, {'decimal_separator': ',', 'thousands_separator': '.'}, '1234'),
])
def test_number_separators_are_explicit_and_do_not_reinterpret_native_exact_numbers(raw, profile, expected):
    assert number_string(raw, profile) == expected


@pytest.mark.parametrize('raw,profile,code', [
    ('12,34.56', {'thousands_separator': ','}, 'INVALID_GROUPING'),
    ('1,234.5,6', {'thousands_separator': ','}, 'INVALID_GROUPING'),
    ('1.234,5.6', {'decimal_separator': ',', 'thousands_separator': '.'}, 'INVALID_GROUPING'),
    ('1,234', {}, 'INVALID_DECIMAL'),
    ('1.2.3', {}, 'INVALID_DECIMAL'),
    ('1E3', {}, 'INVALID_DECIMAL'),
    ('+1.2', {}, 'INVALID_DECIMAL'),
    ('--1', {}, 'INVALID_DECIMAL'),
    (True, {}, 'INVALID_DECIMAL'),
    (1.25, {}, 'INVALID_DECIMAL'),
    (Decimal('NaN'), {}, 'INVALID_DECIMAL'),
    (Decimal('Infinity'), {}, 'INVALID_DECIMAL'),
    (Decimal('0E+10000000'), {}, 'INVALID_DECIMAL'),
    pytest.param(10 ** 10000, {}, 'INVALID_DECIMAL', id='oversized-native-integer'),
    ('1.2', {'decimal_separator': '.', 'thousands_separator': '.'}, 'NUMBER_PROFILE_INVALID'),
    ('1.2', {'decimal_separator': ':'}, 'NUMBER_PROFILE_INVALID'),
    ('1.2', [], 'NUMBER_PROFILE_INVALID'),
])
def test_number_interpretation_never_guesses_or_silently_removes_invalid_grouping(raw, profile, code):
    error(code, number_string, raw, profile)


def test_leading_zeros_unicode_and_explicit_padding_are_preserved_without_invented_recovery():
    text = column('text')
    assert normalize_value('000123', text) == ('000123', None)
    assert normalize_value('Cà phê Đắk Lắk ☕', text) == ('Cà phê Đắk Lắk ☕', None)
    assert normalize_value(123, text) == ('123', None)
    assert normalize_value(123, column('text', pad_width=6)) == ('000123', None)
    assert normalize_value('001', column('choice', choices=['001', '002'])) == ('001', None)
    error('CHOICE_INVALID', normalize_value, '1', column('choice', choices=['001']))
    error('PADDING_INVALID', normalize_value, '1', column('text', pad_width=True))
    error('TEXT_TOO_LONG', normalize_value, 'cafe', column('text', validation={'max_length': 3}))


def test_blank_required_zero_negative_and_whitespace_are_distinct():
    money = column('money')
    assert normalize_value(None, money) == (None, None)
    assert normalize_value('', money) == (None, None)
    assert normalize_value(0, money) == ('0.00', 0)
    assert normalize_value('0', column('money', required=True)) == ('0.00', 0)
    assert normalize_value('-0.01', money) == ('-0.01', -1)
    assert normalize_value(' ', column('text', required=True)) == (' ', None)
    error('REQUIRED', normalize_value, None, column('money', required=True))
    error('REQUIRED', normalize_value, '', column('text', required=True))
    error('INVALID_DECIMAL', normalize_value, ' ', money)
    error('INVALID_DECIMAL', normalize_value, False, money)


def test_precision_scale_money_kg_and_int64_bounds_are_authoritative():
    assert normalize_value('999.99', column('decimal', scale=2, precision=5)) == ('999.99', 99999)
    error('PRECISION_EXCEEDED', normalize_value, '1000', column('decimal', scale=2, precision=5))
    error('EXCESS_PRECISION', normalize_value, '1.001', column('money'))
    error('EXCESS_PRECISION', normalize_value, '1.1', column('integer'))
    assert normalize_value('1.234', column('decimal', scale=3)) == ('1.234', 1234)
    assert normalize_value('92233720368547758.07', column('money', precision=19)) == ('92233720368547758.07', INT64_MAX)
    assert normalize_value('-92233720368547758.08', column('money', precision=19)) == ('-92233720368547758.08', INT64_MIN)
    error('AMOUNT_OVERFLOW', normalize_value, '92233720368547758.08', column('money', precision=19))
    error('AMOUNT_OVERFLOW', normalize_value, '-92233720368547758.09', column('money', precision=19))
    error('AMOUNT_OVERFLOW', normalize_value, '9223372036854775808', column('integer', precision=19))
    error('VALUE_OUT_OF_RANGE', normalize_value, '-1', column('decimal', validation={'min': '0'}))
    error('VALUE_OUT_OF_RANGE', normalize_value, '11', column('decimal', validation={'max': '10'}))


def test_native_decimal_normalization_stays_exact_under_non_dot_locale():
    profile = {'decimal_separator': ',', 'thousands_separator': '.'}
    assert normalize_value('1.234,56', column('money'), profile) == ('1234.56', 123456)
    assert normalize_value(Decimal('1234.56'), column('money'), profile) == ('1234.56', 123456)


@pytest.mark.parametrize('serial,epoch,expected', [
    ('0', '1900', '1899-12-31'), ('1', '1900', '1900-01-01'),
    ('59', '1900', '1900-02-28'), ('61', '1900', '1900-03-01'),
    ('0', '1904', '1904-01-01'), ('1', '1904', '1904-01-02'),
    ('60', '1904', '1904-03-01'), ('2958465', '1900', '9999-12-31'),
])
def test_excel_date_epochs_use_explicit_metadata_without_float(serial, epoch, expected):
    assert normalize_value(serial, column('date'), date_meta={'excel_serial': serial, 'epoch': epoch}) == (expected, None)


@pytest.mark.parametrize('serial,epoch,code', [
    ('60', '1900', 'EXCEL_INVALID_DATE'), ('1', 'bad', 'DATE_EPOCH_INVALID'),
    ('-1', '1900', 'DATE_INVALID'), ('1.5', '1900', 'DATE_INVALID'),
    ('NaN', '1900', 'DATE_INVALID'), ('Infinity', '1900', 'DATE_INVALID'),
    ('2958466', '1900', 'DATE_INVALID'), ('2958465', '1904', 'DATE_INVALID'),
])
def test_invalid_excel_dates_are_not_silently_shifted_or_assumed(serial, epoch, code):
    error(code, normalize_value, serial, column('date'), date_meta={'excel_serial': serial, 'epoch': epoch})


def test_ambiguous_date_text_requires_profile_and_iso_has_one_meaning():
    day = column('date')
    error('DATE_FORMAT_REQUIRED', normalize_value, '01/02/2026', day)
    error('DATE_FORMAT_REQUIRED', normalize_value, '01/02/2026', day, {'date_format': 123})
    assert normalize_value('01/02/2026', day, {'date_format': '%d/%m/%Y'}) == ('2026-02-01', None)
    assert normalize_value('01/02/2026', day, {'date_format': '%m/%d/%Y'}) == ('2026-01-02', None)
    assert normalize_value('2026-02-01', day, {'date_format': '%m/%d/%Y'}) == ('2026-02-01', None)
    error('DATE_INVALID', normalize_value, '31/02/2026', day, {'date_format': '%d/%m/%Y'})
    error('DATE_INVALID', normalize_value, '2026-02-30', day)


def test_text_formula_prefix_is_literal_until_explicit_engine_calculation():
    raw = '=SUM(A1:A2)'
    assert normalize_value(raw, column('text')) == (raw, None)
    assert normalize_value('+cmd', column('text')) == ('+cmd', None)
    error('INVALID_DECIMAL', normalize_value, '=1+2', column('formula'))
    assert FormulaEngine(lambda _: LiteralCell(raw)).evaluate('=A1') == raw
    result = FormulaEngine(lambda _: None).evaluate('=0.1+0.2')
    assert normalize_value(result, column('formula')) == ('0.30', 30)


@pytest.mark.parametrize('raw', ['=1+2', '+cmd', '-cmd', '@SUM(A1)', '  =1', '\t=1', '\r\n+cmd'])
def test_export_protects_untrusted_formula_like_text(raw):
    assert safe_export_text(raw) == "'" + raw


def test_export_preserves_native_negative_numeric_values_and_ordinary_text():
    assert safe_export_text(Decimal('-1.25')) == Decimal('-1.25')
    assert safe_export_text(-2) == -2
    assert safe_export_text(None) is None
    assert safe_export_text('000123') == '000123'
    assert safe_export_text('Cà phê') == 'Cà phê'


def test_fingerprint_is_stable_by_column_id_and_preserves_null_text_zero_distinctions():
    assert fingerprint({'code': '001', 'amount': '0.00'}) == fingerprint({'amount': '0.00', 'code': '001'})
    assert fingerprint({'code': '001', 'amount': '9'}, ['code']) == fingerprint({'code': '001', 'amount': '0'}, ['code'])
    assert len({fingerprint({'code': value}) for value in (None, '', '0', 0, '00')}) == 5
    assert fingerprint({'code': '1'}) != fingerprint({'other': '1'})
    assert fingerprint({'code': '1'}, []) is None
