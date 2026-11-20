Feature: Changing and cancelling boarding reservations

  Scenario: Updating a boarding reservation changes its pet name
    Given an existing boarding reservation to change
    When the boarding reservation is updated with a new pet name
    Then the boarding reservation change succeeds
    And the boarding reservation now shows the new pet name

  Scenario: Updating a boarding reservation with zero nights is rejected
    Given an existing boarding reservation to change
    When the boarding reservation is updated with 0 nights
    Then the boarding reservation change responds with status 400

  Scenario: Updating an unknown boarding reservation returns not found
    When an update is sent for an unknown boarding reservation id
    Then the boarding reservation change responds with status 404

  Scenario: Deleting a boarding reservation succeeds
    Given an existing boarding reservation to change
    When the boarding reservation is deleted
    Then the boarding reservation change succeeds

  Scenario: Deleting the same boarding reservation twice is rejected
    Given an existing boarding reservation to change
    When the boarding reservation is deleted
    Then the boarding reservation change succeeds
    When the boarding reservation is deleted again
    Then the repeated boarding reservation deletion is rejected

  Scenario: Deleting an unknown boarding reservation returns not found
    When a delete is sent for an unknown boarding reservation id
    Then the boarding reservation change responds with status 404
