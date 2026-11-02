import React, { useState } from 'react';
import { ProductList } from '@/pages/products/ProductList';
import { CreateProduct } from '@/pages/products/CreateProduct';
import { PriceList } from '@/pages/prices/PriceList';
import { CreatePrice } from '@/pages/prices/CreatePrice';

type View = 'products' | 'create-product' | 'prices' | 'create-price';

const App: React.FC = () => {
  const [view, setView] = useState<View>('products');

  return (
    <div style={{ maxWidth: '960px', margin: '0 auto', padding: '24px' }}>
      <h1>Station Retrofit</h1>

      <nav style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
        <button onClick={() => setView('products')}>Products</button>
        <button onClick={() => setView('create-product')}>New Product</button>
        <button onClick={() => setView('prices')}>Prices</button>
        <button onClick={() => setView('create-price')}>New Price</button>
      </nav>

      {view === 'products' && <ProductList />}
      {view === 'create-product' && <CreateProduct />}
      {view === 'prices' && <PriceList />}
      {view === 'create-price' && <CreatePrice />}
    </div>
  );
};

export default App;
