Feature: Authentication endpoints
  Invalid logins and malformed tokens are not accepted.

  Scenario Outline: Invalid login attempts are rejected
    When a login is attempted with variant <variant>
    Then the login attempt is rejected with a client error

    Examples:
      | variant      |
      | unknown-user |
      | empty-body   |

  Scenario: A malformed token is not reported as valid
    When a malformed token is submitted for validation
    Then the malformed token is not reported as valid
