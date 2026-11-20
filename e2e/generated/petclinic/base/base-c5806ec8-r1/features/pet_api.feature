Feature: Pet API
  Pet types can be listed and unknown pets are rejected.

  Scenario: Pet types can be listed
    When the client requests the list of pet types
    Then the pet response has status 200
    And the pet types response body is not blank

  Scenario: Fetching a pet with an unknown id is rejected
    When the client fetches a pet with an unknown id
    Then the pet response is a client error

  Scenario: Updating a pet with an unknown id is rejected
    When the client updates a pet with an unknown id
    Then the pet response is a client error
