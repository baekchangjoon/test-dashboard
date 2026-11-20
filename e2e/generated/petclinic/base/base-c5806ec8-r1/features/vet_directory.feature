Feature: Veterinarian directory
  Veterinarians can be listed and unknown veterinarians are rejected.

  Scenario: Listing veterinarians succeeds
    When the client lists all veterinarians
    Then the veterinarian response has status 200

  Scenario: Fetching a veterinarian with an unknown id is rejected
    When the client fetches a veterinarian with an unknown id
    Then the veterinarian response is a client error
