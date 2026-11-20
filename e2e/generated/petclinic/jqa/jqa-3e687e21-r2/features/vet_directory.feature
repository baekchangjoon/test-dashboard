Feature: Veterinarian directory API
  Veterinarians can be listed and fetched individually.

  Scenario: Listing veterinarians succeeds
    When the veterinarian list is requested
    Then the veterinarian request succeeds
    And the veterinarian list response is a list

  Scenario: A listed veterinarian can be fetched individually
    Given the veterinarian list has been retrieved
    When the first listed veterinarian is fetched by id if any exists
    Then the individually fetched veterinarian matches the listed one

  Scenario: Fetching an unknown veterinarian is rejected
    When a veterinarian with an unknown id is requested
    Then the veterinarian request is rejected with a client error
