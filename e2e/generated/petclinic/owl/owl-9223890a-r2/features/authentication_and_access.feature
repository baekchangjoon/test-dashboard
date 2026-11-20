Feature: Authentication and access control
  Protected endpoints require a valid token and invalid logins are refused.

  Scenario Outline: Anonymous requests to protected endpoints are refused
    When an anonymous client sends GET to "<path>"
    Then the access control response status is 401 or 403

    Examples:
      | path              |
      | /api/reservations |
      | /api/owners       |
      | /api/vets         |

  Scenario: A malformed bearer token is refused
    When a client with a malformed bearer token sends GET to "/api/owners"
    Then the access control response status is 401 or 403

  Scenario: Login with an unknown username is rejected
    When a login is attempted for an unknown username
    Then the access control response is a client error

  Scenario: Login with a wrong password is rejected
    When a login is attempted for username "admin" with a random wrong password
    Then the access control response is a client error

  Scenario: Validating a malformed token does not confirm it
    When a malformed token is submitted for validation
    Then the validation response does not confirm the token
