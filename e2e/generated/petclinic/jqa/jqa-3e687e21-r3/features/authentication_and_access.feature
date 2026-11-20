Feature: Authentication and access control
  Protected API endpoints require a valid bearer token, and the auth endpoints reject bogus input.

  Scenario Outline: Anonymous clients cannot read protected resources
    When an anonymous client sends a GET request to "<path>"
    Then the access attempt is refused as unauthenticated

    Examples:
      | path              |
      | /api/reservations |
      | /api/owners       |

  Scenario: Anonymous clients cannot create boarding reservations
    When an anonymous client tries to book a boarding reservation
    Then the access attempt is refused as unauthenticated

  Scenario: A forged bearer token is rejected on a protected endpoint
    When a client with a forged bearer token sends a GET request to "/api/owners"
    Then the access attempt is refused as unauthenticated

  Scenario: Login with an unknown username is rejected
    When a client logs in with a random unknown username
    Then the login attempt fails with a client error status

  Scenario: Validating a forged token does not report it as valid
    When a client asks the auth service to validate a forged token
    Then the forged token is not reported as valid
