Feature: Authentication login

  Scenario Outline: Reject login with a wrong password for a known user name
    When a login is attempted for user "<username>" with a random wrong password
    Then the login attempt is rejected with a client error

    Examples:
      | username |
      | admin    |
      | user     |

  Scenario: Reject login for a user that does not exist
    When a login is attempted for a randomly named user that does not exist
    Then the login attempt is rejected with a client error
