import React from 'react';

interface SimulatedDataNoticeProps {
  /**
   * What the figures below the notice are.
   *
   * The wording has to say plainly that the values are illustrative. Several
   * views render equipment ratings, protection thresholds and degradation
   * figures that are properties of the reference plant rather than
   * measurements of any battery, and an operator has to be able to tell them
   * apart at a glance.
   */
  detail: string;
}

/**
 * The banner every view carries above its figures.
 *
 * The HMI renders values that the simulation produced, or values that are
 * illustrative properties of the reference plant. Both have to be labelled as
 * such: an unlabelled "100.0 % SOH" or "10.0 MW/s" reads as a measurement of
 * real equipment, which is exactly the confusion this banner exists to
 * prevent.
 */
export const SimulatedDataNotice: React.FC<SimulatedDataNoticeProps> = ({ detail }) => (
  <div className="notice-box">
    <strong>SIMULATED DATA ONLY:</strong> {detail}
  </div>
);
