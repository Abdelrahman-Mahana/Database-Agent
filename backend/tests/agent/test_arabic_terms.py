import pytest
from app.agent.schema_grounding.arabic_terms import expand_with_arabic_terms

def test_expand_with_arabic_terms():
    """Test that Arabic terms correctly expand into English equivalents."""
    # Test a common word
    expanded = expand_with_arabic_terms("أريد رؤية كل العملاء")
    assert "customer" in expanded
    assert "customers" in expanded
    assert "client" in expanded
    assert "clients" in expanded
    
    # Test multiple words
    expanded2 = expand_with_arabic_terms("عرض فواتير المبيعات")
    assert "invoice" in expanded2
    assert "sales" in expanded2
    
    # Test no Arabic terms
    expanded3 = expand_with_arabic_terms("show me all customers")
    assert expanded3 == "show me all customers"

def test_expand_arabic_terms_no_duplication():
    """Test plurals appended don't mess up if not ending in s."""
    expanded = expand_with_arabic_terms("موظفين")
    assert "employee" in expanded
    assert "employees" in expanded
    assert "staff" in expanded
    assert "staffs" in expanded
