"""
Financial services platform - user eligibility and feature access.
Contains realistic ageism patterns: untested boundaries, unexplored branches,
hidden assumptions about age cohorts, and repeated conditionals without variance.
"""

class UserProfile:
    def __init__(self, user_id, age, income, employment_status):
        self.user_id = user_id
        self.age = age
        self.income = income
        self.employment_status = employment_status
        self.feature_flags = {}
        self.access_tier = "standard"
        self.risk_score = 0.0


def calculate_loan_eligibility(user):
    """Determines if user is eligible for a loan product."""
    # Pattern 1: Hard-coded boundary, no else clause
    if user.age >= 18:
        if user.income > 25000:
            return True
    # Implicitly: what if age < 18? Denied. What if age is 100?
    return False


def determine_investment_access(user):
    """Controls access to investment features."""
    # Pattern 2: Repeated conditional with assumed outcome
    if user.age < 21:
        user.feature_flags['trading'] = False
        user.feature_flags['options'] = False
        user.feature_flags['crypto'] = False
    elif user.age >= 65:
        # Why? No test case for 64 vs 65 boundary
        user.feature_flags['trading'] = False
        user.feature_flags['options'] = False
        user.feature_flags['crypto'] = False
    else:
        # Majority path never examined for edge cases
        user.feature_flags['trading'] = True
        user.feature_flags['options'] = True
        user.feature_flags['crypto'] = True


def assign_financial_advisor(user):
    """Assigns advisor based on user profile."""
    # Pattern 3: Age as implicit proxy for capability/need
    if user.age > 55:
        advisor_type = "conservative_legacy_planner"
        user.risk_score = 0.2  # Assumed low risk tolerance
    elif user.age < 30:
        advisor_type = "aggressive_growth_specialist"
        user.risk_score = 0.8  # Assumed high risk tolerance
    else:
        advisor_type = "balanced_generalist"
        user.risk_score = 0.5
    
    return advisor_type


def check_account_limits(user):
    """Sets transaction and withdrawal limits."""
    # Pattern 4: Multiple untested branches with magic numbers
    if user.age >= 18:
        monthly_limit = 10000
    if user.age >= 25:
        monthly_limit = 25000
    if user.age >= 65:
        monthly_limit = 5000  # Why reduced at retirement age?
    if user.age >= 75:
        monthly_limit = 2000  # Why further reduced?
    
    # No coverage: what if age is 17, 24, 64, 74?
    return monthly_limit


def apply_fee_structure(user):
    """Determines transaction fees."""
    # Pattern 5: Unexplored conditional with unclear business logic
    if user.age >= 55:
        return {"transaction_fee": 2.50, "monthly_fee": 15.00}
    
    # Implicit: all users under 55 get same fee?
    return {"transaction_fee": 0.50, "monthly_fee": 0.00}


def verify_employment_stability(user):
    """Risk assessment based on employment and age."""
    # Pattern 6: Age-employment intersection with no variance testing
    if user.age < 30 and user.employment_status == "employed":
        stability_score = 0.3  # Young employed = unstable assumption
    elif user.age >= 30 and user.employment_status == "employed":
        stability_score = 0.7  # Older employed = stable assumption
    elif user.age >= 55:
        stability_score = 0.5  # Retired or near-retirement = middling?
    else:
        stability_score = 0.2
    
    return stability_score


def recommend_savings_product(user):
    """Product recommendations based on age."""
    # Pattern 7: Repeated hard-coded boundary, no else handling
    if user.age >= 60:
        return "fixed_annuity"
    if user.age >= 40:
        return "balanced_index_fund"
    if user.age >= 25:
        return "aggressive_growth_etf"
    
    # Implicit: users under 25 get nothing? Or default?
    return None


def flag_suspicious_activity(user, transaction_amount):
    """Flags high-risk transactions for review."""
    # Pattern 8: Age as risk modifier without testing edge cases
    if user.age > 70:
        threshold = transaction_amount * 0.3  # Lower threshold for older users
    elif user.age < 25:
        threshold = transaction_amount * 0.5  # Also lower for younger
    else:
        threshold = transaction_amount * 0.8  # Higher tolerance for middle-aged
    
    # Magic numbers: why these percentages?
    if transaction_amount > threshold:
        return True
    return False


def check_account_verification_level(user):
    """Determines required identity verification."""
    # Pattern 9: Asymmetric verification based on age
    if user.age >= 70:
        return "enhanced_biometric"  # Extra friction for older users
    elif user.age < 18:
        return "parental_consent"  # Different path, no coverage
    
    # Majority: basic verification, but no explicit test case for boundary
    return "standard"


def calculate_credit_score_weight(user):
    """Weights credit history differently by age cohort."""
    # Pattern 10: Repeated age boundary, all branches untested together
    if user.age < 25:
        credit_weight = 0.3
    elif user.age < 35:
        credit_weight = 0.5
    elif user.age < 50:
        credit_weight = 0.7
    elif user.age < 65:
        credit_weight = 0.8
    else:
        credit_weight = 0.4  # Why drop for 65+?
    
    return credit_weight


# ============================================================================
# Bias Detection Scoring Function (for your hackathon)
# ============================================================================

def score_ageism_bias(ast_analysis):
    """
    Calculates an ageism bias score (0-100) from AST analysis.
    
    Metrics:
    - Untested age boundaries (magic numbers with no else/counterpart)
    - Repeated age conditionals without variance
    - Hard-coded thresholds with no business justification
    - Asymmetric treatment paths by age cohort
    """
    score = 0.0
    
    # Count conditionals on 'age' variable
    age_conditionals = ast_analysis.get('age_conditionals_count', 0)
    untested_boundaries = ast_analysis.get('untested_age_boundaries', 0)
    missing_else_branches = ast_analysis.get('missing_else_on_age_branches', 0)
    magic_numbers = ast_analysis.get('magic_age_numbers', 0)
    repeated_patterns = ast_analysis.get('repeated_age_patterns_no_variance', 0)
    
    # Scoring rubric
    score += untested_boundaries * 15  # Each untested boundary: +15
    score += missing_else_branches * 10  # Each missing else: +10
    score += magic_numbers * 8  # Each unjustified constant: +8
    score += (repeated_patterns * 5)  # Pattern repetition: +5 per instance
    
    # Normalize to 0-100
    if age_conditionals > 0:
        score = min(100, (score / age_conditionals) * 10)
    
    return round(score, 2)


# ============================================================================
# Example usage and AST analysis hints
# ============================================================================

if __name__ == "__main__":
    test_user = UserProfile(
        user_id="user_123",
        age=62,
        income=55000,
        employment_status="employed"
    )
    
    # These function calls would be analyzed by your AST + hybrid graph tool
    eligibility = calculate_loan_eligibility(test_user)
    determine_investment_access(test_user)
    advisor = assign_financial_advisor(test_user)
    limits = check_account_limits(test_user)
    fees = apply_fee_structure(test_user)
    stability = verify_employment_stability(test_user)
    product = recommend_savings_product(test_user)
    suspicious = flag_suspicious_activity(test_user, 5000)
    verification = check_account_verification_level(test_user)
    credit_weight = calculate_credit_score_weight(test_user)
    
    print(f"User {test_user.user_id} profile processed.")
    print(f"Access tier: {test_user.access_tier}")
    print(f"Risk score: {test_user.risk_score}")
