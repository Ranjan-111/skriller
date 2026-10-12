import { Workbench } from "../components/workbench";
import { IdentityProvider } from "../components/identity";
export default function Home() {
  return (
    <IdentityProvider>
      <Workbench />
    </IdentityProvider>
  );
}
