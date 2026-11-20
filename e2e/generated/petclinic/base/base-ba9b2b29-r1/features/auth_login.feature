Feature: Login endpoint rejects bad requests

  Scenario: Login with an unknown username is rejected
    When a login is attempted with an unknown username
    Then the login attempt is rejected with a client error

  Scenario: Login with an empty body is rejected
    When a login is attempted with an empty body
    Then the login attempt is rejected with a client error
