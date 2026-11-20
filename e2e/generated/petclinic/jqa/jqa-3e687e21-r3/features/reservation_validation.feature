Feature: Reservation validation and error handling
  Invalid, conflicting or unknown boarding reservations are rejected with documented status codes.

  Scenario: Reject a boarding reservation submitted as an empty JSON object
    When the client submits an empty JSON object as a boarding reservation
    Then the boarding reservation request is rejected with status 400

  Scenario: Reject a boarding reservation submitted without a request body
    When the client submits a boarding reservation without any request body
    Then the boarding reservation request is rejected with status 400

  Scenario Outline: Reject a boarding reservation with a non-positive number of nights
    When the client submits a boarding reservation for a unique pet with <nights> nights
    Then the boarding reservation request is rejected with status 400

    Examples:
      | nights |
      | 0      |
      | -1     |

  Scenario: Reject a boarding reservation with a blank pet name
    When the client submits a boarding reservation with a blank pet name
    Then the boarding reservation request is rejected with status 400

  Scenario: Reject a second boarding reservation for the same room and check-in date
    Given an existing boarding reservation for a unique pet in the validation suite
    When the client books the same room on the same check-in date for another pet
    Then the boarding reservation request is rejected with status 409

  Scenario: Fetching an unknown boarding reservation returns not found
    When the client fetches a boarding reservation with an id that does not exist
    Then the boarding reservation request is rejected with status 404

  Scenario: Updating an unknown boarding reservation returns not found
    When the client updates a boarding reservation with an id that does not exist
    Then the boarding reservation request is rejected with status 404

  Scenario: Deleting an unknown boarding reservation returns not found
    When the client deletes a boarding reservation with an id that does not exist
    Then the boarding reservation request is rejected with status 404
