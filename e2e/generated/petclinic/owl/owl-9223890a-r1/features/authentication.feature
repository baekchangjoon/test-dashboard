Feature: Authentication and access control

  Scenario Outline: Anonymous callers cannot read protected endpoint <path>
    When an anonymous caller sends GET to "<path>"
    Then the access control response status is 401 or 403

    Examples:
      | path              |
      | /api/owners       |
      | /api/reservations |

  Scenario: Anonymous callers cannot book a reservation
    When an anonymous caller tries to book a boarding reservation
    Then the access control response status is 401 or 403

  Scenario: Login with an unknown username is rejected
    When an anonymous caller logs in as an unknown random user
    Then the access control response is a client error

  Scenario: Login as admin with a wrong password is rejected
    When an anonymous caller logs in as "admin" with a random wrong password
    Then the access control response is a client error

  Scenario: Validating a malformed token does not report it as valid
    When an anonymous caller asks to validate the token "not-a-real-token"
    Then the access control validation does not succeed
