Feature: Authentication endpoints
  The login and token validation endpoints reject invalid input.

  Scenario: Login with an unknown username and password is rejected
    When a login is attempted with a random unknown username and password
    Then the authentication response is a client error

  Scenario: Login without a request body is rejected
    When a login is attempted without a request body
    Then the authentication response is a client error

  Scenario: Validating a forged token does not report it as valid
    When a forged token is submitted to the token validation endpoint
    Then the token validation does not report the token as valid
