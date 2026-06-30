"""Tests for preparation converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import (
    AutoFieldNode,
    DataCleansingNode,
    DynamicRenameNode,
    FieldAction,
    FilterNode,
    FormulaNode,
    GenerateRowsNode,
    MultiFieldFormulaNode,
    MultiRowFormulaNode,
    RecordIDNode,
    SampleNode,
    SelectNode,
    SortNode,
    UniqueNode,
)

from .conftest import DEFAULT_CONFIG, make_node


class TestFilterConverter:
    def test_filter_simple_mode(self):
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Field": "Age",
                "Operator": ">",
                "Operands": {"Operand": "18"},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.mode == "simple"
        assert result.expression == "[Age] > 18"

    def test_filter_custom_mode(self):
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Custom",
                "Expression": "[Revenue] &gt; 1000 AND [Active] = &quot;Y&quot;",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.mode == "custom"
        assert "[Revenue] > 1000" in result.expression
        assert '"Y"' in result.expression

    def test_filter_default_simple(self):
        """When Mode is missing, default to simple."""
        node = make_node(
            tool_type="Filter",
            configuration={"Field": "Status", "Operator": "=", "Operands": {"Operand": "Active"}},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.mode == "simple"

    def test_filter_simple_nested_simple_element(self):
        """Older XML nests Field/Operator/Operands under <Simple>."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "Revenue",
                    "Operator": ">",
                    "Operands": {"Operand": "1000"},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.mode == "simple"
        assert result.expression == "[Revenue] > 1000"

    def test_filter_empty_configuration_produces_empty_expression(self):
        """A Filter with no Expression and no Simple-mode fields produces empty expression."""
        node = make_node(
            tool_type="Filter",
            configuration={},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == ""

    def test_filter_simple_contains_operator(self):
        """Contains UI operator should produce Alteryx Contains() function call."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "Name",
                    "Operator": "Contains",
                    "Operands": {"Operand": "1"},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == 'Contains([Name], "1")'

    def test_filter_simple_notcontains_operator(self):
        """NotContains UI operator should produce !Contains(...)."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "InvoicingCategory",
                    "Operator": "NotContains",
                    "Operands": {"Operand": "HVP"},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == '!Contains([InvoicingCategory], "HVP")'

    def test_filter_simple_istrue_operator(self):
        """IsTrue UI operator should produce a bare field-ref boolean expression."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "IsConnected",
                    "Operator": "IsTrue",
                    "Operands": {"Operand": ""},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == "[IsConnected]"

    def test_filter_simple_eq_quotes_string_operand(self):
        """Equality with a string operand must auto-quote so the translator can parse it."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "Test Type",
                    "Operator": "=",
                    "Operands": {"Operand": "S&W"},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == '[Test Type] = "S&W"'

    def test_filter_simple_eq_preserves_field_ref(self):
        """When operand is itself a field ref [Foo], do not wrap in quotes."""
        node = make_node(
            tool_type="Filter",
            configuration={
                "Mode": "Simple",
                "Simple": {
                    "Field": "AccountingPeriod",
                    "Operator": "=",
                    "Operands": {"Operand": "[Production Month]"},
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.expression == "[AccountingPeriod] = [Production Month]"

    def test_filter_custom_mode_empty_expression(self):
        """A Filter in custom mode with no Expression element produces empty expression."""
        node = make_node(
            tool_type="Filter",
            configuration={"Mode": "Custom"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FilterNode)
        assert result.mode == "custom"
        assert result.expression == ""


class TestFormulaConverter:
    def test_formula_single_field(self):
        node = make_node(
            tool_type="Formula",
            configuration={
                "FormulaFields": {
                    "FormulaField": {
                        "@field": "FullName",
                        "@expression": "[First] + &quot; &quot; + [Last]",
                        "@type": "V_WString",
                        "@size": "200",
                    }
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FormulaNode)
        assert len(result.formulas) == 1
        f = result.formulas[0]
        assert f.output_field == "FullName"
        assert '"' in f.expression  # &quot; should be decoded
        assert f.data_type == "V_WString"
        assert f.size == 200

    def test_formula_multiple_fields(self):
        node = make_node(
            tool_type="Formula",
            configuration={
                "FormulaFields": {
                    "FormulaField": [
                        {"@field": "Col_A", "@expression": "[X] + 1", "@type": "Int32"},
                        {"@field": "Col_B", "@expression": "[Y] * 2", "@type": "Double"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FormulaNode)
        assert len(result.formulas) == 2
        assert result.formulas[0].output_field == "Col_A"
        assert result.formulas[1].output_field == "Col_B"


class TestSelectConverter:
    def test_select_fields(self):
        node = make_node(
            tool_type="Select",
            configuration={
                "SelectFields": {
                    "SelectField": [
                        {"@field": "Name", "@selected": "True"},
                        {"@field": "TempCol", "@selected": "False"},
                        {"@field": "OldName", "@selected": "True", "@rename": "NewName"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, SelectNode)
        assert len(result.field_operations) == 3
        assert result.field_operations[0].field_name == "Name"
        assert result.field_operations[0].selected is True
        assert result.field_operations[1].field_name == "TempCol"
        assert result.field_operations[1].selected is False
        assert result.field_operations[1].action == FieldAction.DESELECT
        assert result.field_operations[2].rename_to == "NewName"
        assert result.field_operations[2].action == FieldAction.RENAME


class TestSortConverter:
    def test_sort_ascending_descending(self):
        node = make_node(
            tool_type="Sort",
            configuration={
                "SortInfo": {
                    "Field": [
                        {"@field": "Name", "@order": "Ascending"},
                        {"@field": "Age", "@order": "Descending"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, SortNode)
        assert len(result.sort_fields) == 2
        assert result.sort_fields[0].field_name == "Name"
        assert result.sort_fields[0].ascending is True
        assert result.sort_fields[1].field_name == "Age"
        assert result.sort_fields[1].ascending is False


class TestSampleConverter:
    def test_sample_first_n(self):
        node = make_node(
            tool_type="Sample",
            configuration={"Mode": "First", "N": "100"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, SampleNode)
        assert result.sample_method == "first"
        assert result.n_records == 100


class TestUniqueConverter:
    def test_unique_converter(self):
        node = make_node(
            tool_type="Unique",
            configuration={
                "UniqueFields": {
                    "Field": [
                        {"@field": "CustomerID"},
                        {"@field": "OrderDate"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, UniqueNode)
        assert result.key_fields == ["CustomerID", "OrderDate"]


class TestRecordIDConverter:
    def test_record_id_defaults(self):
        node = make_node(
            tool_type="RecordID",
            configuration={"FieldName": "RowNum", "StartValue": "0"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, RecordIDNode)
        assert result.output_field == "RowNum"
        assert result.starting_value == 0


class TestMultiRowFormulaConverter:
    def test_multi_row_formula(self):
        node = make_node(
            tool_type="MultiRowFormula",
            configuration={
                "Expression": "[Row-1:Value] + [Value]",
                "UpdateField": "RunningSum",
                "NumRows": "1",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, MultiRowFormulaNode)
        assert result.expression == "[Row-1:Value] + [Value]"
        assert result.output_field == "RunningSum"
        assert result.rows_above == 1


class TestMultiFieldFormulaConverter:
    def test_multi_field_formula(self):
        node = make_node(
            tool_type="MultiFieldFormula",
            configuration={
                "Expression": "Trim([_CurrentField_])",
                "Fields": {
                    "Field": [
                        {"@field": "Col_A"},
                        {"@field": "Col_B"},
                    ]
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, MultiFieldFormulaNode)
        assert result.expression == "Trim([_CurrentField_])"
        assert result.fields == ["Col_A", "Col_B"]


class TestDataCleansingConverter:
    def test_data_cleansing(self):
        node = make_node(
            tool_type="DataCleansing",
            configuration={
                "TrimWhitespace": "True",
                "RemoveNull": "True",
                "ReplaceNullsWith": "N/A",
                "ModifyCase": "Upper",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DataCleansingNode)
        assert result.trim_whitespace is True
        assert result.remove_null is True
        assert result.replace_nulls_with == "N/A"
        assert result.modify_case == "upper"


class TestAutoFieldConverter:
    def test_auto_field(self):
        node = make_node(tool_type="AutoField")
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, AutoFieldNode)
        assert len(result.conversion_notes) > 0


class TestGenerateRowsConverter:
    def test_generate_rows(self):
        node = make_node(
            tool_type="GenerateRows",
            configuration={
                "InitExpression": "1",
                "ConditionExpression": "[Row] &lt;= 100",
                "LoopExpression": "[Row] + 1",
                "FieldName": "Row",
                "FieldType": "Int64",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, GenerateRowsNode)
        assert result.init_expression == "1"
        assert "<=" in result.condition_expression  # HTML decoded
        assert result.loop_expression == "[Row] + 1"
        assert result.output_field == "Row"


class TestDynamicRenameConverter:
    def test_dynamic_rename_first_row(self):
        node = make_node(
            tool_type="DynamicRename",
            configuration={"RenameMode": "FirstRow"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DynamicRenameNode)
        assert result.rename_mode == "FirstRow"

    def test_dynamic_rename_default(self):
        node = make_node(tool_type="DynamicRename", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DynamicRenameNode)
        assert result.rename_mode == "FirstRow"  # default

    def test_dynamic_rename_formula_mode(self):
        node = make_node(
            tool_type="DynamicRename",
            configuration={"RenameMode": "Formula"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DynamicRenameNode)
        assert result.rename_mode == "Formula"
