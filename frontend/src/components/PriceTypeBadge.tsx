import React from 'react';
import { PriceType } from '@/api/models/PriceType';

interface PriceTypeBadgeProps {
  type: PriceType;
}

const typeColors: Record<PriceType, { bg: string; text: string }> = {
  [PriceType.Retail]: { bg: '#dbeafe', text: '#1e40af' },
  [PriceType.Wholesale]: { bg: '#f3e8ff', text: '#6b21a8' },
  [PriceType.Partner]: { bg: '#ccfbf1', text: '#115e59' },
};

export const PriceTypeBadge: React.FC<PriceTypeBadgeProps> = ({ type }) => {
  const colors = typeColors[type] ?? { bg: '#f1f5f9', text: '#334155' };

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: 600,
        backgroundColor: colors.bg,
        color: colors.text,
      }}
    >
      {type}
    </span>
  );
};
