Feature: Authentication login endpoint

  Scenario: Login with an unknown username is rejected
    When a login is attempted for a randomly generated unknown username
    Then the login attempt is rejected with a client error

  Scenario: Login with an empty body is rejected
    When a login is attempted with an empty request body
    Then the login attempt is rejected with a client error
